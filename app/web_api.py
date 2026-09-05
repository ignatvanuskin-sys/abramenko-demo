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

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bot_logic import DialogState, reply
from .admin_notify import is_booking_complete, notify_admin

logger = logging.getLogger("abramenko.web")

# Web session store — отдельно от Telegram store, но тот же класс идеи
_WEB_STORE: dict[str, DialogState] = {}
_WEB_SEEN: dict[str, float] = {}
_SESSION_CAP = 2000
_SESSION_TTL = 86400  # 24ч без активности — сессия чистится
# Rate limit: максимум сообщений в окне на одну сессию + глобально по IP
_RATE_LIMIT = 30
_RATE_WINDOW = 60.0
_RATE: dict[str, list] = {}
_IP_RATE_LIMIT = 120
_IP_RATE: dict[str, list] = {}
# Метрики (без секретов и PII)
_METRICS = {"chat_requests": 0, "chat_total_ms": 0.0, "chat_429": 0}
_LAT_MS: list = []
_LAT_CAP = 500


def _p95(values: list) -> float:
    if not values:
        return 0.0
    return sorted(values)[min(len(values) - 1, int(len(values) * 0.95))]

def _prune_sessions(now: float | None = None) -> None:
    import time as _time
    now = now if now is not None else _time.monotonic()
    for sid in [s for s, seen in _WEB_SEEN.items() if now - seen > _SESSION_TTL]:
        _WEB_STORE.pop(sid, None)
        _WEB_SEEN.pop(sid, None)
    while len(_WEB_STORE) > _SESSION_CAP:
        oldest = min(_WEB_SEEN, key=lambda s: _WEB_SEEN[s])
        _WEB_STORE.pop(oldest, None)
        _WEB_SEEN.pop(oldest, None)

def _check_rate(session_id: str, now: float | None = None, limit: int | None = None) -> bool:
    import time as _time
    now = now if now is not None else _time.monotonic()
    arr = [t for t in _RATE.get(session_id, []) if now - t < _RATE_WINDOW]
    if len(arr) >= (limit if limit is not None else _RATE_LIMIT):
        _RATE[session_id] = arr
        return False
    arr.append(now)
    _RATE[session_id] = arr
    return True

def _get_state(session_id: str) -> DialogState:
    import time as _time
    if session_id not in _WEB_STORE:
        _WEB_STORE[session_id] = DialogState()
    _WEB_SEEN[session_id] = _time.monotonic()
    _prune_sessions()
    return _WEB_STORE[session_id]

def _reset_state(session_id: str) -> None:
    import time as _time
    _WEB_STORE[session_id] = DialogState()
    _WEB_SEEN[session_id] = _time.monotonic()

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
    # фронт same-origin, credentials не используются — credentials=False,
    # иначе браузеры отбрасывают комбинацию "*" + credentials
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def _validation_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={"detail": "Некорректный запрос. Проверьте текст сообщения и попробуйте снова."},
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

@app.get("/api/metrics")
def metrics():
    n = _METRICS["chat_requests"]
    avg = _METRICS["chat_total_ms"] / n if n else 0.0
    try:
        from .llm_client import LLM_STATS
    except ImportError:  # pragma: no cover
        from llm_client import LLM_STATS
    return {
        "chat_requests": n,
        "chat_avg_ms": round(avg, 1),
        "chat_p95_ms": round(_p95(_LAT_MS), 1),
        "chat_rate_limited": _METRICS["chat_429"],
        "llm_calls": LLM_STATS.get("calls", 0),
        "llm_failures": LLM_STATS.get("failures", 0),
        "sessions": len(_WEB_STORE),
    }

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import logging as _lg
    log = _lg.getLogger("abramenko.web")
    log.info(
        "startup graph_version=%s has_telegram=%s has_llm=%s has_wa_secret=%s",
        (os.getenv("GRAPH_API_VERSION") or "v21.0"),
        bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        bool(os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")),
        bool(os.getenv("WHATSAPP_APP_SECRET")),
    )
    if (os.getenv("WHATSAPP_ALLOW_UNVERIFIED") or "") == "1":
        log.error("SECURITY: WHATSAPP_ALLOW_UNVERIFIED=1 — подпись вебхука отключена, только для локальной разработки!")
    yield


app.router.lifespan_context = _lifespan

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
async def chat(req: ChatRequest, request: Request):
    import time as _time
    t0 = _time.monotonic()
    sid = (req.session_id or "").strip()
    if not sid:
        sid = str(uuid.uuid4())
    ip = request.client.host if request.client else "unknown"
    if not _check_rate("ip:" + ip, limit=_IP_RATE_LIMIT) or not _check_rate(sid):
        _METRICS["chat_429"] += 1
        raise HTTPException(status_code=429, detail="Слишком много сообщений. Подождите немного и попробуйте снова.")
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
                await notify_admin(bot, st, uid, f"web:{sid[:8]}", premium=True)
            except Exception as e:
                logger.exception("web admin notify failed: %s", e)

    import time as _time2
    _METRICS["chat_requests"] += 1
    _elapsed = (_time2.monotonic() - t0) * 1000
    _METRICS["chat_total_ms"] += _elapsed
    _LAT_MS.append(_elapsed)
    if len(_LAT_MS) > _LAT_CAP:
        del _LAT_MS[: len(_LAT_MS) - _LAT_CAP]
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
