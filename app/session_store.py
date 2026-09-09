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


class PersistentSessionStore:
    """Redis primary + InMemory fallback. Интерфейс как у InMemorySessionStore.

    Рестарт процесса без Redis больше не теряет диалоги, если REDIS_URL настроен.
    Без REDIS_URL ведёт себя ровно как InMemory (ноль новых зависимостей в тестах).
    """

    def __init__(self, prefix: str = "dlg:") -> None:
        self._memory = InMemorySessionStore()
        self._prefix = prefix
        self._redis: RedisSessionStore | None = None
        client = get_redis_client()
        if client is not None:
            self._redis = RedisSessionStore(client, prefix=prefix)
            logger.info("sessions: redis backend prefix=%s", prefix)

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "memory"

    def get(self, user_id: Key) -> DialogState:
        if self._redis is not None:
            try:
                return self._redis.get(user_id)
            except Exception as e:
                logger.warning("redis get failed, memory fallback: %s", e)
        return self._memory.get(user_id)

    def set(self, user_id: Key, state: DialogState) -> None:
        self._memory.set(user_id, state)
        if self._redis is not None:
            try:
                self._redis.set(user_id, state)
            except Exception as e:
                logger.warning("redis set failed: %s", e)

    def reset(self, user_id: Key) -> None:
        self._memory.reset(user_id)
        if self._redis is not None:
            try:
                self._redis.reset(user_id)
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
