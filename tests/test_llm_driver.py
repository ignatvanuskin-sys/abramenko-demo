import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json as _json
import sqlite3
from unittest.mock import patch

from app.bot_logic import DialogState, reply


def _j(reply_text, **fields):
    d = {"reply": reply_text, "intent": "booking", "service": None,
         "branch": None, "client_time": None, "name": None}
    d.update(fields)
    return _json.dumps(d, ensure_ascii=False)


def _seed(db_path):
    c = sqlite3.connect(db_path)
    c.executescript("""
    CREATE TABLE branches (id INTEGER PRIMARY KEY, name TEXT, address TEXT, timezone TEXT, is_active INTEGER);
    INSERT INTO branches VALUES (1, 'Abramenko Studio', 'Букетова 61', 'Asia/Almaty', 1);
    INSERT INTO branches VALUES (2, 'Madame', 'Жамбыла 127', 'Asia/Almaty', 1);
    CREATE TABLE masters (id INTEGER PRIMARY KEY, name TEXT, specialization TEXT, is_active INTEGER);
    INSERT INTO masters VALUES (1, 'Анна', 'колорист', 1);
    CREATE TABLE services (id INTEGER PRIMARY KEY, name TEXT, duration_minutes INTEGER, price_min INTEGER, price_max INTEGER, category TEXT);
    INSERT INTO services VALUES (1, 'Балаяж', 60, 25000, 80000, 'окрашивание');
    CREATE TABLE master_branches (master_id INTEGER, branch_id INTEGER);
    INSERT INTO master_branches VALUES (1, 1);
    INSERT INTO master_branches VALUES (1, 2);
    CREATE TABLE master_services (master_id INTEGER, service_id INTEGER);
    INSERT INTO master_services VALUES (1, 1);
    CREATE TABLE working_hours (id INTEGER PRIMARY KEY, master_id INTEGER, weekday INTEGER, start_time TEXT, end_time TEXT);
    CREATE TABLE schedule_exceptions (id INTEGER PRIMARY KEY, master_id INTEGER, date TEXT, is_day_off INTEGER, custom_start TEXT, custom_end TEXT);
    CREATE TABLE appointments (id INTEGER PRIMARY KEY, branch_id INTEGER, master_id INTEGER, service_id INTEGER, client_name TEXT, client_phone TEXT, starts_at TEXT, ends_at TEXT, status TEXT DEFAULT 'booked', created_at TEXT);
    """)
    for wd in range(6):
        c.execute("INSERT INTO working_hours VALUES (%d, 1, %d, '10:00', '19:00')" % (wd + 1, wd))
    c.commit()
    c.close()


def test_llm_drives_full_booking(monkeypatch, tmp_path):
    db = str(tmp_path / "drv.db")
    _seed(db)
    monkeypatch.setenv("DEMO_BOOKING", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db)
    monkeypatch.setenv("LLM_API_KEY", "sk-test")

    script = [
        _j("Конечно! Какая услуга интересует — окрашивание, стрижка, ногти?"),
        _j("Балаяж — отлично. Какой филиал удобнее: Букетова или Жамбыла?", service="Балаяж"),
        _j("Жамбыла, поняла. Напишите удобные дату и время.", branch="madame"),
        _j("Завтра в 14:00 — хорошо. Как вас зовут?", client_time="завтра в 14:00"),
        _j("Айгерим, приятно! Какой номер для связи?", name="Айгерим"),
        _j("Принято! Ждём вас завтра в 14:00."),  # драйвер-ответ на телефон
        # живое закрытие от ИИ по фактам (7-й вызов)
        "Айгерим, вы записаны на завтра в 14:00 — Жамбыла! Администратор перезвонит для подтверждения.",
    ]
    it = iter(script)

    def fake_call(cfg, messages, temperature):
        try:
            return next(it)
        except StopIteration:
            return _j("Поняла вас.")

    with patch("app.llm_client._call_openai_compatible", side_effect=fake_call):
        s = DialogState()
        r1 = reply(s, "хочу записаться")
        assert "услуга" in r1.lower(), r1
        r2 = reply(s, "балаяж")
        assert "будни или выходные" not in r2.lower(), r2
        r3 = reply(s, "Жамбыла")
        assert "дату" in r3.lower() or "время" in r3.lower(), r3
        r4 = reply(s, "завтра в 14:00")
        assert "зовут" in r4.lower(), r4
        assert s.selected_slot is not None and "14:00" in s.selected_slot
        r5 = reply(s, "Айгерим")
        assert "номер" in r5.lower(), r5
        r6 = reply(s, "+7 707 123 45 67")
        assert s.step == "done", r6
        # живое закрытие с фактами, не шаблон
        assert "14:00" in r6 or "завтра" in r6.lower(), r6

    c = sqlite3.connect(db)
    cnt = c.execute("SELECT COUNT(*) FROM appointments WHERE status='booked'").fetchone()[0]
    c.close()
    assert cnt == 1, "appointment не создан"


def test_llm_repeat_is_not_template(monkeypatch):
    """Кейс пользователя: повтор «хочу записаться» не даёт шаблон про будни."""
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.delenv("DEMO_BOOKING", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with patch("app.llm_client._call_openai_compatible",
               return_value=_j("Записываемся! Какая услуга нужна?")):
        s = DialogState()
        reply(s, "Хочу записаться")
        r = reply(s, "хочу записаться")
        assert "будни или выходные" not in r.lower(), r
        assert isinstance(r, str) and len(r) > 5


def test_llm_empty_twice_falls_back_to_rule_based(monkeypatch):
    """Groq вернул пустое 200 дважды — бот отвечает шаблоном, а не виснет."""
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.delenv("DEMO_BOOKING", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    calls = []
    def fake_empty(cfg, messages, temperature):
        calls.append(1)
        return ""
    with patch("app.llm_client._call_openai_compatible", side_effect=fake_empty):
        s = DialogState()
        r = reply(s, "хочу записаться")
        assert isinstance(r, str) and len(r) > 5
        assert calls == [1, 1], calls  # первая попытка + один ретрай
        # rule-based fallback собрал intent
        assert s.intent == "booking"


def test_llm_history_kept_and_capped(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.delenv("DEMO_BOOKING", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with patch("app.llm_client._call_openai_compatible",
               return_value=_j("Поняла вас, расскажите подробнее.")):
        s = DialogState()
        for i in range(10):
            reply(s, f"сообщение {i}")
        assert len(s.history) <= 8
        assert s.history[0]["role"] == "user"
        # сериализация не теряет историю
        d = s.to_dict()
        s2 = DialogState.from_dict(d)
        assert len(s2.history) == len(s.history)
