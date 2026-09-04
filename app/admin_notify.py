"""Формирование и отправка уведомления администратору.

Ответственность: данные заявки (DialogState) → текст сообщения → send_message.
НЕ решает, когда спрашивать телефон/филиал и какие цены.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("abramenko.admin_notify")

# Используется внутри, чтобы не импортировать Bot на уровне модуля в тестах
ADMIN_ENV = "TELEGRAM_ADMIN_CHAT_ID"


def get_admin_chat_id() -> Optional[int]:
    raw = (os.getenv(ADMIN_ENV) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid %s value: %r", ADMIN_ENV, raw)
        return None


def is_booking_complete(state) -> bool:
    """Определяет завершённость заявки по фактическому состоянию DialogState.

    Не по тексту ответа, а по полям. Требует наличия всех ключевых данных
    и step == 'done'. Intent может быть booking/model/vacancy/training — все
    ветки собирают одинаковый набор (услуга/время/филиал/имя/телефон).
    """
    return (
        getattr(state, "step", None) == "done"
        and getattr(state, "phone", None)
        and getattr(state, "name", None)
        and getattr(state, "branch", None)
        and getattr(state, "time_pref", None)
        and getattr(state, "service", None)
        and getattr(state, "intent", None) is not None
    )


def build_admin_message(state, user_id: int, username: Optional[str]) -> str:
    """Собирает текст для администратора только из реально существующих данных."""
    service = getattr(state, "service", None) or "—"
    time_pref = getattr(state, "time_pref", None) or "—"
    branch = getattr(state, "branch", None) or "—"
    name = getattr(state, "name", None) or "—"
    phone = getattr(state, "phone", None) or "—"

    if username:
        tg_line = f"@{username}\nID: {user_id}"
    else:
        tg_line = f"без username\nID: {user_id}"

    # Эмодзи как в ТЗ, но без HTML — plain text
    return (
        "🔔 Новая заявка\n"
        "\n"
        f"💇 Услуга: {service}\n"
        f"🗓 Когда: {time_pref}\n"
        f"📍 Филиал: {branch}\n"
        f"👤 Имя: {name}\n"
        f"📞 Телефон: {phone}\n"
        "\n"
        "Telegram:\n"
        f"{tg_line}"
    )


async def notify_admin(bot, state, user_id: int, username: Optional[str]) -> bool:
    """Отправляет уведомление администратору. Возвращает True если отправлено.

    Не кидает исключение наружу — логирует и возвращает False при ошибке.
    """
    admin_id = get_admin_chat_id()
    if admin_id is None:
        logger.warning(
            "TELEGRAM_ADMIN_CHAT_ID not configured — admin notification skipped user_id=%s",
            user_id,
        )
        return False

    # Защита от дублей: один завершённый диалог → одно уведомление
    if getattr(state, "_admin_notified", False):
        logger.info("admin notification already sent for user_id=%s, skip", user_id)
        return False

    if not is_booking_complete(state):
        logger.warning(
            "notify_admin called for incomplete state user_id=%s step=%s",
            user_id, getattr(state, "step", None),
        )
        return False

    text = build_admin_message(state, user_id, username)
    # Флаг ставим ДО отправки, чтобы повторный вызов в том же состоянии не дублировал
    try:
        setattr(state, "_admin_notified", True)
    except Exception:
        pass

    try:
        await bot.send_message(chat_id=admin_id, text=text)
        logger.info("admin notification sent to %s for user_id=%s", admin_id, user_id)
        return True
    except Exception as e:
        logger.exception("admin notification failed admin_id=%s user_id=%s: %s", admin_id, user_id, e)
        return False
