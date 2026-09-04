"""Тесты админ-уведомлений. 6 сценариев из ТЗ этапа 3."""
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.admin_notify import build_admin_message, get_admin_chat_id, is_booking_complete, notify_admin
from app.bot_logic import DialogState, reply


def _complete_state() -> DialogState:
    s = DialogState()
    reply(s, "здравствуйте, хочу балаяж")
    reply(s, "окрашены, был кератин")
    reply(s, "в субботу утром")
    reply(s, "Жамбыла")
    reply(s, "Айгерим")
    reply(s, "+7 707 123 45 67")
    assert s.step == "done"
    return s


def test_admin_notification_sent(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "999")
    s = _complete_state()
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=None)
    import asyncio
    asyncio.run(notify_admin(bot, s, 123456789, "testuser"))
    bot.send_message.assert_called_once()
    # вызвали с правильным chat_id
    assert bot.send_message.call_args.kwargs["chat_id"] == 999


def test_admin_notification_content(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "999")
    s = _complete_state()
    bot = AsyncMock()
    import asyncio
    asyncio.run(notify_admin(bot, s, 123456789, "testuser"))
    text = bot.send_message.call_args.kwargs["text"]
    assert "Балаяж" in text or "балаяж" in text.lower()
    assert "Жамбыла" in text
    assert "Айгерим" in text
    assert "+7 707 123 45 67" in text
    assert "123456789" in text
    assert "@testuser" in text


def test_admin_notification_without_username(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "999")
    s = _complete_state()
    bot = AsyncMock()
    import asyncio
    asyncio.run(notify_admin(bot, s, 123456789, None))
    text = bot.send_message.call_args.kwargs["text"]
    assert "без username" in text
    assert "123456789" in text


def test_admin_chat_id_missing_no_crash(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)
    # на случай если .env подтянул старое значение
    if "TELEGRAM_ADMIN_CHAT_ID" in os.environ:
        monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)
    s = _complete_state()
    bot = AsyncMock()
    import asyncio
    result = asyncio.run(notify_admin(bot, s, 1, "u"))
    assert result is False
    bot.send_message.assert_not_called()
    # клиентский сценарий: состояние всё ещё done, бот не упал
    assert s.step == "done"


def test_admin_api_error_does_not_break_booking(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "999")
    s = _complete_state()
    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
    import asyncio
    # не должно кидать исключение наружу
    result = asyncio.run(notify_admin(bot, s, 1, "u"))
    assert result is False
    # клиент всё равно получил финальный ответ — состояние не сломано
    assert s.step == "done"
    assert s.phone == "+7 707 123 45 67"


def test_admin_notification_is_not_duplicated(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "999")
    s = _complete_state()
    bot = AsyncMock()
    import asyncio
    asyncio.run(notify_admin(bot, s, 1, "u"))
    asyncio.run(notify_admin(bot, s, 1, "u"))
    # вторая попытка должна быть проигнорирована флагом
    assert bot.send_message.call_count == 1


def test_admin_notification_not_sent_for_incomplete(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "999")
    s = DialogState()
    reply(s, "здравствуйте, хочу балаяж")
    # ещё не done
    assert not is_booking_complete(s)
    bot = AsyncMock()
    import asyncio
    result = asyncio.run(notify_admin(bot, s, 1, "u"))
    assert result is False
    bot.send_message.assert_not_called()


def test_get_admin_chat_id_parsing(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "  123  ")
    assert get_admin_chat_id() == 123
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "abc")
    assert get_admin_chat_id() is None
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "")
    assert get_admin_chat_id() is None


def test_build_admin_message_uses_real_data():
    s = DialogState()
    s.service = "Стрижка"
    s.time_pref = "Будни утром"
    s.branch = "Букетова, 61"
    s.name = "Мария"
    s.phone = "+7 705 111 22 33"
    text = build_admin_message(s, 42, None)
    assert "Мария" in text
    assert "Стрижка" in text
    assert "без username" in text
    assert "42" in text
