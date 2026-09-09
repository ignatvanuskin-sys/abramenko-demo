import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, timedelta
from app.bot_logic import (
    DialogState, reply, _parse_date_ru, _parse_time_ru, _handle_time_input,
)


def test_parse_date_ru():
    today = date(2026, 9, 9)  # среда
    assert _parse_date_ru("завтра", today) == date(2026, 9, 10)
    assert _parse_date_ru("сегодня", today) == today
    assert _parse_date_ru("послезавтра", today) == date(2026, 9, 11)
    assert _parse_date_ru("в субботу", today) == date(2026, 9, 12)
    assert _parse_date_ru("в среду", today) == today
    assert _parse_date_ru("12 сентября", today) == date(2026, 9, 12)
    assert _parse_date_ru("12.09", today) == date(2026, 9, 12)
    assert _parse_date_ru("привет", today) is None


def test_parse_time_ru():
    assert _parse_time_ru("в 14:00") == (14, 0)
    assert _parse_time_ru("завтра в 9:30") == (9, 30)
    assert _parse_time_ru("к 15 часам") == (15, 0)
    assert _parse_time_ru("в субботу утром") == (10, 0)
    assert _parse_time_ru("вечером") == (18, 0)
    assert _parse_time_ru("днём") == (13, 0)
    assert _parse_time_ru("привет") is None


def test_time_flow_full_and_partial():
    s = DialogState()
    s.step = "await_slot"
    r = _handle_time_input(s, "завтра в 14:00")
    assert s.step == "await_name", r
    assert s.selected_slot is not None and "14:00" in s.selected_slot
    assert "завтра" in s.time_pref

    s2 = DialogState()
    s2.step = "await_slot"
    r2 = _handle_time_input(s2, "завтра")
    assert s2.step == "await_slot" and s2.selected_slot is None
    assert "во сколько" in r2.lower()
    r3 = _handle_time_input(s2, "в 14:00")
    assert s2.step == "await_name", r3
    assert "14:00" in s2.selected_slot

    s3 = DialogState()
    s3.step = "await_slot"
    r4 = _handle_time_input(s3, "в 14:00")
    assert s3.step == "await_slot" and "на какой день" in r4.lower()
    r5 = _handle_time_input(s3, "завтра")
    assert s3.step == "await_name", r5


def test_time_flow_rejects_past_and_night():
    s = DialogState()
    s.step = "await_slot"
    r = _handle_time_input(s, "вчера в 14:00")
    assert s.selected_slot is None and s.step == "await_slot"
    assert "уже прошло" in r.lower()

    s2 = DialogState()
    s2.step = "await_slot"
    r2 = _handle_time_input(s2, "завтра в 23:00")
    assert s2.selected_slot is None
    assert "10:00" in r2 and "19:00" in r2


def test_no_slot_numbers_in_booking_flow(monkeypatch, tmp_path):
    """Полный флоу без DEMO-БД: время — свободный текст, цифр-выбора нет."""
    monkeypatch.delenv("DEMO_BOOKING", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = DialogState()
    reply(s, "хочу подстричься")   # -> time
    reply(s, "завтра в 14:00")     # предпочтение текстом -> branch
    assert s.step == "branch"
    assert "1, 2 или 3" not in reply(s, "Жамбыла").lower()
    assert s.step == "await_name"
    reply(s, "Айгерим")
    r = reply(s, "+7 707 123 45 67")
    assert s.step == "done"
    assert "14:00" in r or "завтра" in r.lower()
