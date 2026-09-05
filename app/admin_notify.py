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

    Не по тексту ответа, а по полям. Для booking требует service/branch/name/phone + (time_pref или selected_slot+master),
    для vacancy/model/training — service/name/phone (portfolio опционален, время/филиал не требуются).
    """
    if getattr(state, "step", None) != "done":
        return False
    if not getattr(state, "phone", None) or not getattr(state, "name", None) or not getattr(state, "service", None):
        return False
    intent = getattr(state, "intent", None)
    if intent not in ("booking", "vacancy", "model", "training"):
        return False
    if intent == "booking":
        has_branch = bool(getattr(state, "branch", None) or getattr(state, "branch_id", None))
        has_time = bool(getattr(state, "time_pref", None) or getattr(state, "selected_slot", None))
        return has_branch and has_time
    # vacancy/model/training — достаточно базы
    return True


def build_admin_message(state, user_id: int, username: Optional[str]) -> str:
    """Собирает текст для администратора только из реально существующих данных."""
    import html as _html
    # пользовательский ввод экранируем: сообщение уходит в Telegram с parse_mode=HTML
    service = _html.escape(str(getattr(state, "service", None) or "—"), quote=False)
    branch = _html.escape(str(getattr(state, "branch", None) or "—"), quote=False)
    name = _html.escape(str(getattr(state, "name", None) or "—"), quote=False)
    phone = _html.escape(str(getattr(state, "phone", None) or "—"), quote=False)
    # время: либо selected_slot (реальные слоты), либо time_pref (демо)
    time_str = getattr(state, "selected_slot", None) or getattr(state, "time_pref", None) or "—"
    # форматируем ISO в локальное время если это слот
    if getattr(state, "selected_slot", None):
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo("Asia/Almaty"))
            time_str = dt.astimezone(ZoneInfo("Asia/Almaty")).strftime("%d.%m %Y %H:%M")
        except Exception:
            pass
    master = getattr(state, "master_name", None) or getattr(state, "master_id", None) or "—"
    if master != "—" and isinstance(master, int):
        master = f"ID {master}"

    if username:
        tg_line = f"@{username}\nID: {user_id}"
    else:
        tg_line = f"без username\nID: {user_id}"

    # DEMO: если это реальные слоты — показываем подтверждённую запись
    is_real = bool(getattr(state, "selected_slot", None))
    header = "🔔 Подтверждённая запись" if is_real else "🔔 Новая заявка"
    master_line = f"👨‍🎨 Мастер: {master}\n" if is_real and master != "—" else ""

    return (
        f"{header}\n"
        "\n"
        f"💇 Услуга: {service}\n"
        f"📍 Филиал: {branch}\n"
        f"{master_line}"
        f"🗓 Когда: {time_str}\n"
        f"👤 Имя: {name}\n"
        f"📞 Телефон: {phone}\n"
        "\n"
        "Telegram:\n"
        f"{tg_line}"
    )


async def notify_admin(bot, state, user_id: int, username: Optional[str], premium: bool = False) -> bool:
    """Отправляет уведомление администратору. Возвращает True если отправлено.

    Не кидает исключение наружу — логирует и возвращает False при ошибке.
    premium=True — заменить эмодзи на Telegram Premium (<tg-emoji>).
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
    if premium:
        try:
            from .tg_premium import premium as _premium
        except ImportError:  # pragma: no cover
            from tg_premium import premium as _premium
        text = _premium(text)
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
