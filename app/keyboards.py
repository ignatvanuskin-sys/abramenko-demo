"""Клавиатуры для Telegram-UX. Только helpers — логика остаётся в bot_logic.py."""
from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

# Один вопрос за сообщение — клавиатуры лишь подсказывают следующий ответ,
# но не заставляют пользователя жать именно кнопку.

def kb_services() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Окрашивание"), KeyboardButton(text="Стрижка")],
            [KeyboardButton(text="Ногти"), KeyboardButton(text="Другое")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите услугу",
    )


def kb_time() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Будни"), KeyboardButton(text="Выходные")],
            [KeyboardButton(text="Утром"), KeyboardButton(text="Вечером")],
            [KeyboardButton(text="Будни утром"), KeyboardButton(text="Выходные вечером")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Когда удобнее?",
    )


def kb_branch() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Букетова, 61")],
            [KeyboardButton(text="Жамбыла, 127 (Madame)")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите филиал",
    )


def kb_contact_request() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Поделиться контактом", request_contact=True)],
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
