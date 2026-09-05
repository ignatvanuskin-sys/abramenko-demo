"""WhatsApp Cloud API transport — тонкий адаптер поверх bot_logic.

Не трогает bot_logic, admin_notify, llm_client, web.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Dict, Set

import httpx
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse

from .bot_logic import DialogState, reply
from .admin_notify import is_booking_complete, notify_admin

logger = logging.getLogger("abramenko.whatsapp")

# In-memory stores — отдельный адаптер, заменяется на Redis/Postgres без изменения bot_logic
_WA_STORE: Dict[str, DialogState] = {}
_WA_SEEN: Dict[str, float] = {}
# dedup как ordered-dict: sliding window, вытесняем самые старые (без полного clear)
_WA_DEDUP: Dict[str, None] = {}
_DEDUP_CAP = 5000
_SESSION_CAP = 2000
_SESSION_TTL = 86400  # 24ч без активности — сессия чистится
# WhatsApp text message лимит Meta — 4096, webhook body режем раньше
_MAX_BODY = 1_000_000

GRAPH_VERSION_DEFAULT = "v21.0"

def _get_state(wa_id: str) -> DialogState:
    import time as _time
    now = _time.monotonic()
    if wa_id not in _WA_STORE:
        _WA_STORE[wa_id] = DialogState()
    _WA_SEEN[wa_id] = now
    _prune_sessions(now)
    return _WA_STORE[wa_id]

def _prune_sessions(now: float | None = None) -> None:
    import time as _time
    now = now if now is not None else _time.monotonic()
    # сначала протухшие по TTL
    for sid in [s for s, seen in _WA_SEEN.items() if now - seen > _SESSION_TTL]:
        _WA_STORE.pop(sid, None)
        _WA_SEEN.pop(sid, None)
    # затем самые старые при переполнении
    while len(_WA_STORE) > _SESSION_CAP:
        oldest = min(_WA_SEEN, key=lambda s: _WA_SEEN[s])
        _WA_STORE.pop(oldest, None)
        _WA_SEEN.pop(oldest, None)

def _is_dedup(message_id: str) -> bool:
    return message_id in _WA_DEDUP

def _mark_dedup(message_id: str) -> None:
    _WA_DEDUP[message_id] = None
    # sliding window: вытесняем самые старые, а не чистим всё
    while len(_WA_DEDUP) > _DEDUP_CAP:
        _WA_DEDUP.pop(next(iter(_WA_DEDUP)))

def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = (os.getenv("WHATSAPP_APP_SECRET") or "").strip()
    if not secret:
        # fail-closed: без секрета принимаем только явный dev-режим
        # В production WHATSAPP_APP_SECRET обязателен, иначе любой шлёт фейковые сообщения
        if (os.getenv("WHATSAPP_ALLOW_UNVERIFIED") or "") == "1":
            return True
        return False
    if not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)

def _parse_whatsapp_message(payload: dict):
    """Извлекает wa_id, message_id, text. Возвращает None если не текстовое или malformed."""
    try:
        entry = payload.get("entry") or []
        if not entry:
            return None
        changes = entry[0].get("changes") or []
        if not changes:
            return None
        value = changes[0].get("value") or {}
        # игнорируем статусы (delivery/read)
        messages = value.get("messages")
        if not messages or not isinstance(messages, list):
            return None
        msg = messages[0]
        if msg.get("type") != "text":
            return None
        wa_id = msg.get("from")
        msg_id = msg.get("id")
        text = (msg.get("text") or {}).get("body", "")
        if not wa_id or not msg_id:
            return None
        return {"wa_id": wa_id, "message_id": msg_id, "text": text}
    except Exception:
        return None

def _get_bot():
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return None
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    except Exception:
        return None

async def _process_whatsapp_message(wa_id: str, message_id: str, text: str):
    if _is_dedup(message_id):
        logger.info("whatsapp dedup skip message_id=%s wa_id=%s", message_id, wa_id)
        return
    _mark_dedup(message_id)
    state = _get_state(wa_id)
    try:
        reply_text = reply(state, text)
    except Exception as e:
        logger.exception("whatsapp reply failed wa_id=%s: %s", wa_id, e)
        reply_text = "Что-то пошло не так, попробуйте ещё раз."
    # Meta Send
    await _send_whatsapp_message(wa_id, reply_text)
    # admin notify если done
    if is_booking_complete(state) or state.step == "done":
        bot = _get_bot()
        if bot is not None:
            try:
                # wa_id как user_id для админа (хеш)
                uid = abs(hash(wa_id)) % 900000000 + 100000000
                await notify_admin(bot, state, uid, f"wa:{wa_id[:8]}", premium=True)
            except Exception as e:
                logger.exception("whatsapp admin notify failed: %s", e)

async def _send_whatsapp_message(wa_id: str, text: str):
    token = (os.getenv("WHATSAPP_TOKEN") or os.getenv("WHATSAPP_ACCESS_TOKEN") or "").strip()
    phone_id = (os.getenv("PHONE_NUMBER_ID") or "").strip()
    version = (os.getenv("GRAPH_API_VERSION") or GRAPH_VERSION_DEFAULT).strip()
    if not token or not phone_id:
        logger.warning("whatsapp send skipped: missing token/phone_id wa_id=%s", wa_id)
        return
    url = f"https://graph.facebook.com/{version}/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": wa_id, "type": "text", "text": {"body": text[:4096]}}
    import asyncio as _asyncio
    # retry с backoff на 5xx/timeout (429 от Meta — ждём и пробуем раз)
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if 200 <= resp.status_code < 300:
                    logger.info("whatsapp sent to %s status=%s", wa_id, resp.status_code)
                    return
                if resp.status_code == 429:
                    logger.warning("whatsapp 429 wa_id=%s body=%s", wa_id, resp.text[:200])
                    if attempt == 0:
                        await _asyncio.sleep(2)
                        continue
                    return
                if 400 <= resp.status_code < 500:
                    logger.warning("whatsapp 4xx wa_id=%s status=%s body=%s", wa_id, resp.status_code, resp.text[:200])
                    return
                logger.warning("whatsapp 5xx wa_id=%s status=%s attempt=%s", wa_id, resp.status_code, attempt)
                if attempt == 0:
                    await _asyncio.sleep(2)
                    continue
                return
        except httpx.TimeoutException:
            logger.warning("whatsapp timeout wa_id=%s attempt=%s", wa_id, attempt)
            if attempt == 0:
                await _asyncio.sleep(2)
                continue
            return
        except Exception as e:
            logger.exception("whatsapp send failed wa_id=%s: %s", wa_id, e)
            return

router = APIRouter()

@router.get("/webhook/whatsapp")
async def whatsapp_verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    expected = (os.getenv("WHATSAPP_VERIFY_TOKEN") or "").strip()
    if mode == "subscribe" and token == expected and expected:
        return PlainTextResponse(content=challenge or "", status_code=200)
    raise HTTPException(status_code=403, detail="verification failed")

@router.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        logger.warning("whatsapp body too large: %d bytes", len(raw))
        raise HTTPException(status_code=413, detail="payload too large")
    sig = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(raw, sig):
        # fail-closed: не логируем секрет, не логируем полный payload с PII
        logger.warning("whatsapp signature failed")
        raise HTTPException(status_code=403, detail="invalid signature")
    try:
        payload = await request.json()
    except Exception:
        # malformed payload — не падать, вернуть 200 чтобы Meta не ретраил бесконечно, но не обрабатывать
        logger.warning("whatsapp malformed json")
        return {"status": "ok"}
    parsed = _parse_whatsapp_message(payload)
    if not parsed:
        # не текстовое или статусный callback — игнор без ошибки
        return {"status": "ok"}
    # быстрый ACK, обработка в фоне
    background_tasks.add_task(_process_whatsapp_message, parsed["wa_id"], parsed["message_id"], parsed["text"])
    return {"status": "ok"}

# для тестов: сброс
def _reset_for_tests():
    _WA_STORE.clear()
    _WA_SEEN.clear()
    _WA_DEDUP.clear()
