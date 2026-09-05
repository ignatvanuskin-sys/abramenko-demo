import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bot_logic import (
    DialogState, reply, is_off_topic, is_inappropriate, is_unclear,
    OFF_TOPIC_REPLY, UNCLEAR_REPLY, FAQ_UNKNOWN_REPLY, INAPPROPRIATE_REPLY,
    GREETING_FULL,
)
from app.admin_notify import is_booking_complete


def test_programming_is_off_topic_not_utochnyu():
    s = DialogState()
    r = reply(s, "программирование")
    assert r == OFF_TOPIC_REPLY
    assert "Уточню" not in r
    assert s.intent is None and s.step == "start"


def test_best_programmer_is_off_topic():
    s = DialogState()
    r = reply(s, "как стать лучшим программистом")
    assert r == OFF_TOPIC_REPLY
    assert s.intent is None


def test_unclear_single_letter_no_repeat_greeting():
    s = DialogState()
    r1 = reply(s, "ы")
    assert r1 == GREETING_FULL
    r2 = reply(s, "ы")
    assert r2 == UNCLEAR_REPLY
    assert "Здравствуйте" not in r2
    assert s.intent is None and s.step == "start"


def test_faq_unknown_keratin():
    s = DialogState()
    r = reply(s, "делаете кератин?")
    assert r == FAQ_UNKNOWN_REPLY
    assert s.intent is None


def test_inappropriate_no_lead_no_repeat():
    s = DialogState()
    r = reply(s, "ты тупая дура")
    assert r == INAPPROPRIATE_REPLY
    assert "дура" not in r.lower()
    assert s.intent is None and s.step == "start"
    assert not is_booking_complete(s)


def test_inappropriate_inside_booking_ignored_as_slot():
    # внутри booking короткие ответы — не inappropriate-блок для валидных слотов;
    # оскорбление там тоже не должно собирать лид
    s = DialogState()
    reply(s, "хочу балаяж")
    assert s.intent == "booking"


def test_greeting_once_then_unclear():
    s = DialogState()
    r1 = reply(s, "й")
    assert "Здравствуйте" in r1
    r2 = reply(s, "й")
    assert r2 == UNCLEAR_REPLY
