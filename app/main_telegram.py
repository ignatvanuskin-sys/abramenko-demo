"""Telegram-транспорт для готовой логики bot_logic.py.

Запуск: python -m app.main_telegram
Без TELEGRAM_BOT_TOKEN завершается с сообщением, без traceback.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

class _UserIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        if not hasattr(record, "user_id"):
            record.user_id = "-"
        return True

logger = logging.getLogger("abramenko.telegram")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s user_id=%(user_id)s %(message)s",
    )
    # aiogram и другие сторонние логгеры не передают user_id — подставляем дефолт
    for h in logging.getLogger().handlers:
        h.addFilter(_UserIdFilter())
    logging.getLogger().addFilter(_UserIdFilter())
    # покроем уже созданные логгеры aiogram
    for name in ("aiogram", "aiogram.dispatcher", "aiogram.event"):
        logging.getLogger(name).addFilter(_UserIdFilter())

PHONE_RE = re.compile(r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")

FALLBACK_ERROR_TEXT = (
    "Что-то пошло не так, попробуйте ещё раз. "
    "Если не получается — напишите нам в WhatsApp +7 707 486 54 37."
)
WELCOME_TEXT = "Здравствуйте! Abramenko Studio. Что вас интересует — запись, модель, вакансия или обучение?"


def mask_phone(text: str) -> str:
    """Маскирует телефоны в тексте для логов."""
    def _mask(m: re.Match) -> str:
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) >= 4:
            return raw[:-4] + "****"
        return "***"
    return PHONE_RE.sub(_mask, text)


def mask_text_for_log(text: Optional[str]) -> str:
    if not text:
        return ""
    masked = mask_phone(text)
    if len(masked) > 120:
        return masked[:120] + "…"
    return masked


def get_token() -> str:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def _extra(user_id: int, username: Optional[str] = None) -> dict:
    return {"user_id": user_id if user_id is not None else "-", "username": username or "-"}


async def main() -> None:
    token = get_token()
    if not token:
        # Понятная ошибка без traceback — требуется ТЗ п.8/12.
        # В production засыпаем, чтобы не спамить перезапусками — Railway покажет CRASHED до настройки секретов.
        msg = "TELEGRAM_BOT_TOKEN is not configured"
        print(msg, file=sys.stderr)
        logger.error(msg, extra={"user_id": "-"})
        # Пауза уменьшает restart-шторм (Railway restartPolicy ON_FAILURE)
        await asyncio.sleep(15)
        sys.exit(1)

    # Ленивый импорт — позволяет импортировать модуль в тестах без aiogram
    from aiogram import Bot, Dispatcher, F
    from aiogram.filters import Command
    from aiogram.types import Message
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from .admin_notify import notify_admin
    from .bot_logic import DialogState, reply
    from .keyboards import keyboard_for_step, kb_remove
    from .session_store import InMemorySessionStore

    store = InMemorySessionStore()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def on_start(msg: Message) -> None:
        uid = msg.from_user.id if msg.from_user else 0
        uname = msg.from_user.username if msg.from_user else None
        logger.info("cmd /start", extra={"user_id": uid})
        try:
            store.reset(uid)
            store.get(uid).greeted = True
            kb = keyboard_for_step(store.get(uid).step)
            await msg.answer(WELCOME_TEXT, reply_markup=kb)
            logger.info("sent welcome", extra={"user_id": uid})
        except Exception as e:
            logger.exception("on_start failed: %s", e, extra={"user_id": uid})
            try:
                await msg.answer(FALLBACK_ERROR_TEXT, reply_markup=kb_remove())
            except Exception:
                pass

    @dp.message(Command("help"))
    async def on_help(msg: Message) -> None:
        uid = msg.from_user.id if msg.from_user else 0
        await msg.answer(
            "Напишите, что вас интересует: запись, модель, вакансия или обучение. "
            "Я задам пару уточняющих вопросов и передам администратору.",
            reply_markup=kb_remove(),
        )
        logger.info("cmd /help", extra={"user_id": uid})

    # Контакт (кнопка Поделиться контактом)
    @dp.message(F.contact)
    async def on_contact(msg: Message) -> None:
        uid = msg.from_user.id if msg.from_user else 0
        uname = msg.from_user.username if msg.from_user else None
        contact = msg.contact
        phone = contact.phone_number if contact else ""
        # aiogram отдаёт номер без +, нормализуем
        text = phone if phone.startswith("+") else f"+{phone}" if phone else ""
        state: DialogState = store.get(uid)
        logger.info(
            "in contact phone=%s step=%s", mask_phone(text), state.step,
            extra={"user_id": uid},
        )
        try:
            answer = reply(state, text)
        except Exception as e:
            logger.exception("reply(contact) failed: %s", e, extra={"user_id": uid})
            await msg.answer(FALLBACK_ERROR_TEXT, reply_markup=kb_remove())
            return
        kb = keyboard_for_step(state.step)
        # После done убираем клавиатуру
        if state.step == "done":
            kb = kb_remove()
        logger.info(
            "out step=%s phone_masked=%s", state.step, mask_phone(text or ""),
            extra={"user_id": uid},
        )
        await msg.answer(answer, reply_markup=kb)
        # Админ-уведомление — одно на заявку, не ломает клиентский флоу
        try:
            await notify_admin(bot, state, uid, uname)
        except Exception as e:
            logger.exception("admin notify wrapper failed: %s", e, extra={"user_id": uid})

    @dp.message(F.text)
    async def on_text(msg: Message) -> None:
        uid = msg.from_user.id if msg.from_user else 0
        uname = msg.from_user.username if msg.from_user else None
        raw = msg.text or ""
        # Пустое сообщение — не падаем
        if not raw.strip():
            logger.warning("empty text", extra={"user_id": uid})
            await msg.answer("Напишите, пожалуйста, текстом — я подскажу.", reply_markup=kb_remove())
            return
        state: DialogState = store.get(uid)
        log_in = mask_text_for_log(raw)
        logger.info("in text='%s' step=%s intent=%s", log_in, state.step, state.intent, extra={"user_id": uid})
        try:
            answer = reply(state, raw)
        except Exception as e:
            logger.exception("reply failed: %s", e, extra={"user_id": uid})
            await msg.answer(FALLBACK_ERROR_TEXT, reply_markup=kb_remove())
            return
        kb = keyboard_for_step(state.step)
        if state.step == "done":
            kb = kb_remove()
        # Логируем результат без раскрытия телефона
        log_out = mask_text_for_log(answer)
        logger.info(
            "out step=%s intent=%s answer='%s'",
            state.step, state.intent, log_out, extra={"user_id": uid},
        )
        try:
            await msg.answer(answer, reply_markup=kb)
        except Exception as e:
            # Ошибка Telegram API — не падаем
            logger.exception("send failed: %s", e, extra={"user_id": uid})
            try:
                await msg.answer(FALLBACK_ERROR_TEXT, reply_markup=kb_remove())
            except Exception:
                pass
        # Админ-уведомление — не по тексту ответа, а по фактическому состоянию
        try:
            await notify_admin(bot, state, uid, uname)
        except Exception as e:
            logger.exception("admin notify wrapper failed: %s", e, extra={"user_id": uid})

    # Любые другие типы сообщений — мягкий ответ
    @dp.message()
    async def on_other(msg: Message) -> None:
        uid = msg.from_user.id if msg.from_user else 0
        logger.warning("unsupported content_type=%s", msg.content_type, extra={"user_id": uid})
        try:
            await msg.answer("Пришлите, пожалуйста, сообщение текстом.", reply_markup=kb_remove())
        except Exception:
            pass

    logger.info("Telegram bot starting polling", extra={"user_id": "-"})
    print("Telegram-бот запущен. Нажмите Ctrl+C для остановки.", file=sys.stderr)
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("polling cancelled", extra={"user_id": "-"})
    except KeyboardInterrupt:
        logger.info("interrupted", extra={"user_id": "-"})
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
        logger.info("Telegram bot stopped", extra={"user_id": "-"})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\nОстановлено.", file=sys.stderr)
