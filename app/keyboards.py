"""Клавиатуры для Telegram-UX. Только helpers — логика остаётся в bot_logic.py."""
from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from .tg_premium import ICON_BRANCH, ICON_BRUSH, ICON_CONTACT, ICON_TIME

# Один вопрос за сообщение — клавиатуры лишь подсказывают следующий ответ,
# но не заставляют пользователя жать именно кнопку.

def kb_services() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Окрашивание", icon_custom_emoji_id=ICON_BRUSH), KeyboardButton(text="Стрижка")],
            [KeyboardButton(text="Ногти"), KeyboardButton(text="Другое")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите услугу",
    )


def kb_time() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Будни", icon_custom_emoji_id=ICON_TIME), KeyboardButton(text="Выходные", icon_custom_emoji_id=ICON_TIME)],
            [KeyboardButton(text="Утром", icon_custom_emoji_id=ICON_TIME), KeyboardButton(text="Вечером", icon_custom_emoji_id=ICON_TIME)],
            [KeyboardButton(text="Будни утром", icon_custom_emoji_id=ICON_TIME), KeyboardButton(text="Выходные вечером", icon_custom_emoji_id=ICON_TIME)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Когда удобнее?",
    )


def kb_branch() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Букетова, 61", icon_custom_emoji_id=ICON_BRANCH)],
            [KeyboardButton(text="Жамбыла, 127 (Madame)", icon_custom_emoji_id=ICON_BRANCH)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите филиал",
    )


def kb_contact_request() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Поделиться контактом", request_contact=True, icon_custom_emoji_id=ICON_CONTACT)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def kb_remove() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def keyboard_for_step(step: str):
    """Подсказывает клавиатуру под следующий шаг DialogState.step."""
    if step == "clarify":
        # когда ветка ещё не ясна или booking без уточнения услуги
        return kb_services()
    if step == "time":
        return kb_time()
    if step == "branch":
        return kb_branch()
    if step == "await_phone":
        return kb_contact_request()
    if step in ("await_name", "done"):
        return kb_remove()
    return None
