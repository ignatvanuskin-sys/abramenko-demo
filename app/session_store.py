"""Хранилище сессий диалога. Redis при наличии REDIS_URL, иначе in-memory.

Контракт: get/set/reset по ключу (int для Telegram, str для web/WhatsApp).
bot_logic.py менять не нужно — сериализация через DialogState.to_dict/from_dict.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, Union

from .bot_logic import DialogState

logger = logging.getLogger("abramenko.sessions")

Key = Union[int, str]
_TTL = 86400  # 24ч без активности — как TTL in-memory сессий


def get_redis_client():
    """Ленивый Redis-клиент по REDIS_URL. None если не настроен/недоступен.

    Импорт redis тоже ленивый, чтобы тесты и lean-установки работали без пакета.
    """
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return None
    try:
        import redis
    except ImportError:
        logger.warning("REDIS_URL set but redis package not installed — using memory")
        return None
    try:
        client = redis.Redis.from_url(url, socket_timeout=3, socket_connect_timeout=3,
                                      decode_responses=True)
        client.ping()
        return client
    except Exception as e:
        logger.warning("redis unavailable (%s) — using memory fallback", e)
        return None


class InMemorySessionStore:
    """MVP-хранилище: один DialogState на user_id в памяти процесса."""

    def __init__(self) -> None:
        self._data: Dict[Key, DialogState] = {}

    def get(self, user_id: Key) -> DialogState:
        if user_id not in self._data:
            self._data[user_id] = DialogState()
        return self._data[user_id]

    def set(self, user_id: Key, state: DialogState) -> None:
        self._data[user_id] = state

    def reset(self, user_id: Key) -> None:
        self._data[user_id] = DialogState()

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class RedisSessionStore:
    """Persistent-хранилище: DialogState как JSON в Redis с TTL 24ч.

    При любой ошибке Redis бросает исключение — вызывающий код должен
    ловить и падать на InMemory (см. PersistentSessionStore).
    """

    def __init__(self, client, prefix: str = "dlg:") -> None:
        self._r = client
        self._prefix = prefix

    def _key(self, user_id: Key) -> str:
        return f"{self._prefix}{user_id}"

    def get(self, user_id: Key) -> DialogState:
        raw = self._r.get(self._key(user_id))
        if not raw:
            return DialogState()
        try:
            state = DialogState.from_dict(json.loads(raw))
        except Exception:
            return DialogState()
        # refresh TTL при активности
        try:
            self._r.expire(self._key(user_id), _TTL)
        except Exception:
            pass
        return state

    def set(self, user_id: Key, state: DialogState) -> None:
        self._r.setex(self._key(user_id), _TTL, json.dumps(state.to_dict(), ensure_ascii=False))

    def reset(self, user_id: Key) -> None:
        try:
            self._r.delete(self._key(user_id))
        except Exception:
            pass


class PostgresSessionStore:
    """Persistent-хранилище в том же Postgres, что и бронирования.

    Ноль новой инфраструктуры: таблица dialog_states (key/state/updated_at),
    TTL 24ч чистится лениво при чтении. Работает и на SQLite (локальный демо-режим).
    Все операции best-effort — при ошибке бросают исключение, вызывающий падает на память.
    """

    def __init__(self, db_url: str, prefix: str = "dlg:") -> None:
        from sqlalchemy import create_engine
        self._prefix = prefix
        connect_args = {"connect_timeout": 3} if db_url.startswith("postgres") else {}
        self._engine = create_engine(db_url, connect_args=connect_args, pool_pre_ping=True)
        self._init_table()

    def _init_table(self) -> None:
        from sqlalchemy import text
        with self._engine.connect() as c:
            c.execute(text(
                "CREATE TABLE IF NOT EXISTS dialog_states ("
                "k TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TIMESTAMPTZ DEFAULT NOW())"
                if "sqlite" not in str(self._engine.url)
                else "CREATE TABLE IF NOT EXISTS dialog_states ("
                     "k TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            ))
            c.commit()

    def _key(self, user_id: Key) -> str:
        return f"{self._prefix}{user_id}"

    def get(self, user_id: Key) -> DialogState:
        from sqlalchemy import text
        with self._engine.connect() as c:
            row = c.execute(
                text("SELECT state FROM dialog_states WHERE k=:k "
                     "AND updated_at > NOW() - INTERVAL '24 hours'"
                     if "sqlite" not in str(self._engine.url)
                     else "SELECT state FROM dialog_states WHERE k=:k "
                          "AND updated_at > datetime('now','-1 day')"),
                {"k": self._key(user_id)}).fetchone()
        if not row:
            return DialogState()
        try:
            return DialogState.from_dict(json.loads(row[0]))
        except Exception:
            return DialogState()

    def set(self, user_id: Key, state: DialogState) -> None:
        from sqlalchemy import text
        payload = json.dumps(state.to_dict(), ensure_ascii=False)
        with self._engine.connect() as c:
            if "sqlite" not in str(self._engine.url):
                c.execute(text(
                    "INSERT INTO dialog_states(k, state, updated_at) VALUES(:k,:s,NOW()) "
                    "ON CONFLICT(k) DO UPDATE SET state=:s, updated_at=NOW()"),
                    {"k": self._key(user_id), "s": payload})
            else:
                c.execute(text(
                    "INSERT INTO dialog_states(k, state, updated_at) VALUES(:k,:s,CURRENT_TIMESTAMP) "
                    "ON CONFLICT(k) DO UPDATE SET state=:s, updated_at=CURRENT_TIMESTAMP"),
                    {"k": self._key(user_id), "s": payload})
            c.commit()

    def reset(self, user_id: Key) -> None:
        from sqlalchemy import text
        try:
            with self._engine.connect() as c:
                c.execute(text("DELETE FROM dialog_states WHERE k=:k"), {"k": self._key(user_id)})
                c.commit()
        except Exception:
            pass


class PersistentSessionStore:
    """Redis → Postgres → InMemory. Интерфейс как у InMemorySessionStore.

    Цепочка persistent-backend'ов: REDIS_URL если задан, иначе Postgres
    (DATABASE_URL, та же БД что бронирования — ноль новой инфраструктуры),
    иначе память. Рестарт процесса диалоги больше не теряет, если настроен
    хотя бы DATABASE_URL. Без обоих ведёт себя ровно как InMemory.
    """

    def __init__(self, prefix: str = "dlg:") -> None:
        self._memory = InMemorySessionStore()
        self._prefix = prefix
        self._redis: RedisSessionStore | None = None
        self._pg: PostgresSessionStore | None = None
        client = get_redis_client()
        if client is not None:
            self._redis = RedisSessionStore(client, prefix=prefix)
            logger.info("sessions: redis backend prefix=%s", prefix)
        else:
            db_url = (os.getenv("DATABASE_URL") or "").strip()
            if db_url:
                try:
                    self._pg = PostgresSessionStore(db_url, prefix=prefix)
                    logger.info("sessions: postgres backend prefix=%s", prefix)
                except Exception as e:
                    logger.warning("postgres sessions unavailable (%s) — memory fallback", e)
                    self._pg = None

    @property
    def backend(self) -> str:
        if self._redis is not None:
            return "redis"
        if self._pg is not None:
            return "postgres"
        return "memory"

    def _primary_get(self, user_id: Key) -> DialogState | None:
        if self._redis is not None:
            try:
                return self._redis.get(user_id)
            except Exception as e:
                logger.warning("redis get failed, trying next: %s", e)
        if self._pg is not None:
            try:
                return self._pg.get(user_id)
            except Exception as e:
                logger.warning("postgres get failed, memory fallback: %s", e)
        return None

    def _primary_set(self, user_id: Key, state: DialogState) -> None:
        if self._redis is not None:
            try:
                self._redis.set(user_id, state)
                return
            except Exception as e:
                logger.warning("redis set failed, trying postgres: %s", e)
        if self._pg is not None:
            try:
                self._pg.set(user_id, state)
            except Exception as e:
                logger.warning("postgres set failed: %s", e)

    def get(self, user_id: Key) -> DialogState:
        # persistent primary — источник правды (пережил рестарт);
        # память — только L1-копия для скорости внутри процесса
        if self._redis is not None or self._pg is not None:
            state = self._primary_get(user_id)
            if state is not None:
                self._memory.set(user_id, state)
                return state
        return self._memory.get(user_id)

    def set(self, user_id: Key, state: DialogState) -> None:
        self._memory.set(user_id, state)
        if self._redis is not None or self._pg is not None:
            self._primary_set(user_id, state)

    def reset(self, user_id: Key) -> None:
        self._memory.reset(user_id)
        if self._redis is not None:
            try:
                self._redis.reset(user_id)
            except Exception:
                pass
        if self._pg is not None:
            try:
                self._pg.reset(user_id)
            except Exception:
                pass


# Backwards-compat: старый импорт InMemorySessionStore продолжает работать.
SessionStore = InMemorySessionStore


def load_persistent_state(client, prefix: str, key: Key) -> DialogState | None:
    """Загрузить состояние из Redis. None если нет/битое (вызывающий использует L1)."""
    try:
        raw = client.get(f"{prefix}{key}")
    except Exception:
        return None
    if not raw:
        return None
    try:
        return DialogState.from_dict(json.loads(raw))
    except Exception:
        return None


def save_persistent_state(client, prefix: str, key: Key, state: DialogState) -> None:
    """Сохранить состояние в Redis best-effort (ошибки глотаются)."""
    try:
        client.setex(f"{prefix}{key}", _TTL, json.dumps(state.to_dict(), ensure_ascii=False))
    except Exception as e:
        logger.warning("redis save failed %s%s: %s", prefix, key, e)


# Общий persistent KV для web/WhatsApp L2: Redis → Postgres → None.
# Кэшируется на процесс, все операции best-effort.
_shared_pg: PostgresSessionStore | None | str = "uninit"
_shared_pg_tried_redis = False


def _shared_backends():
    global _shared_pg
    r = get_redis_client()
    if r is not None:
        return ("redis", r)
    if _shared_pg == "uninit":
        db_url = (os.getenv("DATABASE_URL") or "").strip()
        if db_url:
            try:
                _shared_pg = PostgresSessionStore(db_url, prefix="")
            except Exception as e:
                logger.warning("shared postgres sessions unavailable: %s", e)
                _shared_pg = None
        else:
            _shared_pg = None
    if _shared_pg is not None:
        return ("postgres", _shared_pg)
    return ("memory", None)


def sessions_backend_name() -> str:
    return _shared_backends()[0]


def load_shared_state(prefix: str, key: Key) -> DialogState | None:
    """L2-загрузка для web/WhatsApp: переживает рестарт. None → создать новое."""
    kind, store = _shared_backends()
    if kind == "memory":
        return None
    try:
        if kind == "redis":
            return load_persistent_state(store, prefix, key)
        # postgres store создан с prefix="" — подставляем префикс вручную
        raw_key = f"{prefix}{key}"
        from sqlalchemy import text
        with store._engine.connect() as c:
            row = c.execute(
                text("SELECT state FROM dialog_states WHERE k=:k"), {"k": raw_key}).fetchone()
        if not row:
            return None
        return DialogState.from_dict(json.loads(row[0]))
    except Exception:
        return None


def save_shared_state(prefix: str, key: Key, state: DialogState) -> None:
    """L2-сохранение для web/WhatsApp, best-effort."""
    kind, store = _shared_backends()
    if kind == "memory":
        return
    try:
        if kind == "redis":
            save_persistent_state(store, prefix, key, state)
            return
        from sqlalchemy import text
        payload = json.dumps(state.to_dict(), ensure_ascii=False)
        with store._engine.connect() as c:
            if "sqlite" not in str(store._engine.url):
                c.execute(text(
                    "INSERT INTO dialog_states(k, state, updated_at) VALUES(:k,:s,NOW()) "
                    "ON CONFLICT(k) DO UPDATE SET state=:s, updated_at=NOW()"),
                    {"k": f"{prefix}{key}", "s": payload})
            else:
                c.execute(text(
                    "INSERT INTO dialog_states(k, state, updated_at) VALUES(:k,:s,CURRENT_TIMESTAMP) "
                    "ON CONFLICT(k) DO UPDATE SET state=:s, updated_at=CURRENT_TIMESTAMP"),
                    {"k": f"{prefix}{key}", "s": payload})
            c.commit()
    except Exception as e:
        logger.warning("shared save failed %s%s: %s", prefix, key, e)
