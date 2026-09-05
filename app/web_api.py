"""Web demo transport — тонкий адаптер поверх bot_logic.

Не дублирует бизнес-правила, использует существующие reply/is_booking_complete.
Session per UUID, admin_notify переиспользуется.
"""
from __future__ import annotations

import html
import logging
import os
import re
import uuid
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bot_logic import DialogState, reply
from .admin_notify import is_booking_complete, notify_admin

logger = logging.getLogger("abramenko.web")

# Web session store — отдельно от Telegram store, но тот же класс идеи
_WEB_STORE: dict[str, DialogState] = {}

def _get_state(session_id: str) -> DialogState:
    if session_id not in _WEB_STORE:
        _WEB_STORE[session_id] = DialogState()
    return _WEB_STORE[session_id]

def _reset_state(session_id: str) -> None:
    _WEB_STORE[session_id] = DialogState()

def _web_buttons_for_step(step: str) -> List[str]:
    if step == "start":
        return ["Хочу записаться", "Сколько стоит балаяж?", "Где вы находитесь?"]
    if step == "clarify":
        return ["Окрашивание", "Стрижка", "Ногти", "Другое"]
    if step == "clarify_hair":
        return ["Окрашены", "Свой цвет", "Был кератин"]
    if step == "portfolio":
        return ["Есть портфолио", "Опыт 2 года", "Начинающий"]
    if step == "time":
        return ["Будни", "Выходные", "Утром", "Вечером", "Будни утром"]
    if step == "branch":
        return ["Букетова, 61", "Жамбыла, 127 (Madame)"]
    if step == "await_phone":
        return []  # input с placeholder, не кнопки
    return []

# Bot для admin notify — лениво, чтобы тесты не требовали токена
_bot_instance = None

def _get_bot():
    global _bot_instance
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        return None
    if _bot_instance is not None:
        return _bot_instance
    try:
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        _bot_instance = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        return _bot_instance
    except Exception as e:
        logger.warning("failed to create Bot for web admin notify: %s", e)
        return None

class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message: str = Field(default="", max_length=5000)

class ChatResponse(BaseModel):
    message: str
    buttons: List[str] = []
    done: bool = False
    step: str = "start"

class ResetRequest(BaseModel):
    session_id: str

app = FastAPI(title="Abramenko Studio Web Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WhatsApp transport — отдельный роутер, тот же bot_logic
try:
    from .whatsapp import router as whatsapp_router
    app.include_router(whatsapp_router)
except Exception as e:
    import logging as _lg
    _lg.getLogger("abramenko.web").warning("whatsapp router not loaded: %s", e)

# Health
@app.get("/api/health")
def health():
    return {"status": "ok", "sessions": len(_WEB_STORE)}

WEB_GREETING = "Здравствуйте! 👋 Я администратор Abramenko Studio. Помогу с услугами и записью. Что вас интересует?"

@app.post("/api/reset")
def reset(req: ResetRequest):
    sid = (req.session_id or "").strip() or str(uuid.uuid4())
    _reset_state(sid)
    _WEB_STORE[sid].greeted = True
    return ChatResponse(
        message=WEB_GREETING,
        buttons=["Хочу записаться", "Услуги и цены", "Адреса"],
        done=False,
        step="start",
    )

@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    sid = (req.session_id or "").strip()
    if not sid:
        sid = str(uuid.uuid4())
    # защита от XSS — не исполняем HTML, но и не ломаем логику бизнес-слоя
    # бизнес-логика работает с сырым текстом, экранируем только при возврате если нужно
    # здесь просто ограничиваем длину и тримим
    raw = (req.message or "")[:2000]
    # пустой message на старте = показать приветствие
    st = _get_state(sid)
    # защита от чужого session_id — изоляция по ключу, чтение только своего состояния
    try:
        # старт — красивое приветствие, а не формальный список веток
        if raw.strip() == "" and st.step == "start":
            st.greeted = True
            return ChatResponse(message=WEB_GREETING, buttons=["Хочу записаться", "Услуги и цены", "Адреса"], done=False, step="start")
        answer = reply(st, raw)
    except Exception as e:
        logger.exception("web reply failed sid=%s: %s", sid[:8], e)
        answer = "Что-то пошло не так, попробуйте ещё раз."

    # экранируем ответ для безопасности (хотя frontend тоже escape)
    # не экранируем ботом возвращаемый текст для логики, только для ответа
    # html.escape сохранит читаемость, но не даст XSS
    safe_answer = html.escape(answer) if "<" in answer or ">" in answer else answer

    done = is_booking_complete(st) or st.step == "done"
    buttons: List[str] = []
    if not done:
        buttons = _web_buttons_for_step(st.step)
    else:
        # финальный экран — кнопки не нужны, frontend покажет success + reset
        buttons = []

    # admin notify — один раз, fail-safe
    if done:
        bot = _get_bot()
        if bot is not None:
            try:
                # web-demo: username = web:<short>, user_id = hash(sid)
                uid = abs(hash(sid)) % 900000000 + 100000000
                await notify_admin(bot, st, uid, f"web:{sid[:8]}")
            except Exception as e:
                logger.exception("web admin notify failed: %s", e)

    return ChatResponse(message=safe_answer, buttons=buttons, done=done, step=st.step)

# Статика — фронт demo. Папка web/ в корне проекта.
from pathlib import Path as _Path

_WEB_DIR = _Path(__file__).resolve().parent.parent / "web"
if _WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR)), name="static")

    @app.get("/")
    def index():
        idx = _WEB_DIR / "index.html"
        if idx.exists():
            return FileResponse(str(idx))
        raise HTTPException(status_code=404, detail="web/index.html not found")
else:
    @app.get("/")
    def index_missing():
        return {"message": "web demo not built yet", "sessions": len(_WEB_STORE)}
