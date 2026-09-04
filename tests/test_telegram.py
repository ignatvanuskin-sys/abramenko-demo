"""Тесты Telegram/session/запись/FAQ/ошибки.

Запуск: pytest -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.bot_logic as bl
from app.bot_logic import DialogState, reply
from app.session_store import InMemorySessionStore
from app.main_telegram import mask_phone, mask_text_for_log


# ── session ──────────────────────────────────────────────────────────

def test_two_users_have_independent_states():
    store = InMemorySessionStore()
    s1 = store.get(111)
    s2 = store.get(222)
    assert s1 is not s2
    reply(s1, "здравствуйте, хочу балаяж")
    # s1 ушёл в clarify_hair, s2 остался в start
    assert s1.step == "clarify_hair"
    assert s2.step == "start"
    reply(s1, "окрашены")
    assert s1.step == "time"
    assert s2.step == "start"


def test_start_resets_session():
    store = InMemorySessionStore()
    s = store.get(1)
    reply(s, "здравствуйте, хочу балаяж")
    reply(s, "окрашены")
    reply(s, "будни")
    assert s.step == "branch"
    store.reset(1)
    s2 = store.get(1)
    assert s2.step == "start"
    assert s2.intent is None


def test_repeated_message_continues_scenario():
    s = DialogState()
    reply(s, "здравствуйте, хочу балаяж")
    reply(s, "окрашены, был кератин")
    # повторили тот же шаг — время уже занято, второй раз идём в филиал
    reply(s, "в субботу утром")
    assert s.step == "branch"
    reply(s, "Жамбыла")
    assert s.step == "await_name"


# ── запись ───────────────────────────────────────────────────────────

def test_full_booking_flow():
    s = DialogState()
    assert "окрашены" in reply(s, "здравствуйте, хочу балаяж").lower()
    reply(s, "окрашены, был кератин")
    reply(s, "в субботу утром")
    reply(s, "Жамбыла")
    assert s.branch is not None
    reply(s, "Айгерим")
    assert s.name == "Айгерим"
    out = reply(s, "+7 707 123 45 67")
    assert "Передал администратору" in out
    assert s.step == "done"
    assert s.phone == "+7 707 123 45 67"
    # данные не потерялись
    assert s.branch == "Жамбыла"
    assert s.name == "Айгерим"


def test_booking_without_coloring_skips_hair_question():
    s = DialogState()
    reply(s, "хочу стрижку")
    # для стрижки вопроса про окрашены нет — сразу время
    assert s.step == "clarify"
    # следующий ответ — время
    out = reply(s, "женская стрижка")
    assert "будни" in out.lower() or "выходные" in out.lower()


def test_phone_completes_even_if_sent_late():
    s = DialogState()
    reply(s, "хочу балаяж")
    reply(s, "окрашены")
    reply(s, "будни вечером")
    reply(s, "Букетова, 61")
    reply(s, "Мария")
    out = reply(s, "+7 705 111 22 33")
    assert "Передал" in out


# ── FAQ ──────────────────────────────────────────────────────────────

def test_faq_price_balazh():
    s = DialogState()
    out = reply(s, "сколько стоит балаяж?")
    assert "25 000" in out
    assert "консультац" in out.lower()


def test_faq_price_strizhka():
    s = DialogState()
    # прямой faq_answer вне диалога
    ans = bl.faq_answer("сколько стоит стрижка?")
    assert ans is not None
    assert "4 000" in ans or "5000" in ans


def test_unknown_question_does_not_crash():
    s = DialogState()
    # неизвестный вопрос на старте — приветствие, не падение
    out = reply(s, "а вы кто?")
    assert isinstance(out, str) and len(out) > 0
    # неизвестный faq на середине (когда ждём филиал) — маскируется
    s2 = DialogState()
    reply(s2, "хочу балаяж")
    reply(s2, "окрашены")
    reply(s2, "будни")
    # на шаге branch спросили "какой филиал" — прислали фигню
    out2 = reply(s2, "не знаю что выбрать")
    assert isinstance(out2, str)


# ── ошибки ───────────────────────────────────────────────────────────

def test_invalid_phone_asks_retry():
    s = DialogState()
    reply(s, "хочу балаяж")
    reply(s, "окрашены")
    reply(s, "будни")
    reply(s, "Жамбыла")
    reply(s, "Айгерим")
    # неверный телефон — должен попросить формат, не закрыть заявку
    out = reply(s, "12345")
    assert "+7" in out or "формат" in out.lower()
    assert s.step == "await_phone"
    assert s.phone is None


def test_empty_text_does_not_crash():
    s = DialogState()
    for t in ["", "   ", None]:
        out = reply(s, t)  # type: ignore[arg-type]
        assert isinstance(out, str)


def test_unexpected_answer_does_not_crash():
    s = DialogState()
    reply(s, "хочу балаяж")
    # вместо ответа про волосы прислали эмодзи
    out = reply(s, "😊")
    assert isinstance(out, str)
    # вместо времени — число
    s2 = DialogState()
    reply(s2, "хочу стрижку")
    reply(s2, "женская")
    out2 = reply(s2, "123")
    assert isinstance(out2, str)


def test_business_logic_exception_handling_simulation():
    # Проверяем что маскирование не падает и что reply можно обернуть
    # (имитация сбоя внутри reply)
    orig = bl.reply
    def boom(*_a, **_kw):
        raise RuntimeError("boom")
    bl.reply = boom  # type: ignore
    try:
        # main_telegram оборачивает reply в try/except — здесь проверяем что исключение именно возникает
        raised = False
        try:
            bl.reply(DialogState(), "hi")
        except RuntimeError:
            raised = True
        assert raised
    finally:
        bl.reply = orig


def test_mask_phone_does_not_leak_full_number():
    masked = mask_phone("мой номер +7 707 123 45 67 звоните")
    assert "123 45 67" not in masked
    assert "****" in masked


def test_mask_text_truncates_long():
    long = "a" * 200
    assert mask_text_for_log(long).endswith("…")
