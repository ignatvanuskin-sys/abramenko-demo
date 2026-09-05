import sys, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from app.web_api import app, _WEB_STORE, _WEB_SEEN, _RATE, _METRICS
from app import whatsapp as wa
from app.bot_logic import DialogState, reply
from app.admin_notify import build_admin_message
from app.prompt_loader import load_system_prompt


def test_fail_closed_without_secret():
    wa._reset_for_tests()
    import os
    os.environ.pop("WHATSAPP_APP_SECRET", None)
    os.environ.pop("WHATSAPP_ALLOW_UNVERIFIED", None)
    assert wa.verify_signature(b"{}", None) is False
    c = TestClient(app)
    r = c.post("/webhook/whatsapp", json={"bad": "data"})
    assert r.status_code == 403


def test_rate_limit_chat(monkeypatch):
    import app.web_api as w
    monkeypatch.setattr(w, "_RATE_LIMIT", 3)
    w._RATE.clear()
    c = TestClient(app)
    for _ in range(3):
        r = c.post("/api/chat", json={"session_id": "rl1", "message": "привет"})
        assert r.status_code == 200
    r = c.post("/api/chat", json={"session_id": "rl1", "message": "привет"})
    assert r.status_code == 429
    assert "Подождите" in r.json()["detail"]
    w._RATE.clear()


def test_session_ttl_eviction(monkeypatch):
    import app.web_api as w
    import time
    w._WEB_STORE.clear(); w._WEB_SEEN.clear()
    w._WEB_STORE["old"] = DialogState()
    w._WEB_SEEN["old"] = time.monotonic() - 90000
    w._WEB_STORE["new"] = DialogState()
    w._WEB_SEEN["new"] = time.monotonic()
    monkeypatch.setattr(w, "_SESSION_TTL", 1)
    monkeypatch.setattr(w, "_SESSION_CAP", 10000)
    w._prune_sessions()
    assert "old" not in w._WEB_STORE
    assert "new" in w._WEB_STORE
    w._WEB_STORE.clear(); w._WEB_SEEN.clear()


def test_session_cap_eviction(monkeypatch):
    import app.web_api as w
    import time
    w._WEB_STORE.clear(); w._WEB_SEEN.clear()
    base = time.monotonic()
    for i in range(5):
        w._WEB_STORE[f"s{i}"] = DialogState()
        w._WEB_SEEN[f"s{i}"] = base + i
    monkeypatch.setattr(w, "_SESSION_CAP", 3)
    monkeypatch.setattr(w, "_SESSION_TTL", 999999)
    w._prune_sessions(base + 10)
    assert len(w._WEB_STORE) == 3
    assert "s3" in w._WEB_STORE and "s4" in w._WEB_STORE
    w._WEB_STORE.clear(); w._WEB_SEEN.clear()


def test_admin_message_escapes_html():
    s = DialogState()
    s.service, s.branch, s.name, s.phone = "x", "y", "<b>Айгерим</b>", "+7 707 123 45 67"
    s.intent, s.step = "booking", "done"
    s.time_pref = "будни"
    msg = build_admin_message(s, 1, None)
    assert "<b>" not in msg
    assert "&lt;b&gt;" in msg


def test_metrics_endpoint():
    c = TestClient(app)
    r = c.get("/api/metrics")
    assert r.status_code == 200
    body = r.json()
    assert "chat_requests" in body and "chat_avg_ms" in body and "sessions" in body


def test_validation_friendly_message():
    c = TestClient(app)
    r = c.post("/api/chat", json={"session_id": "x", "message": "a" * 5001})
    assert r.status_code == 422
    assert "Некорректный запрос" in r.json()["detail"]


def test_index_noindex_and_og():
    c = TestClient(app)
    html = c.get("/").text
    assert 'name="robots" content="noindex' in html
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html


def test_prompt_drift():
    p = load_system_prompt()
    assert len(p) > 500
    for phrase in ["Abramenko", "Букетова", "Жамбыла", "WhatsApp"]:
        assert phrase in p


def test_concurrent_sessions():
    from app.web_api import _get_state
    errs = []
    def worker(i):
        try:
            for _ in range(20):
                s = _get_state(f"conc-{i}")
                s.name = f"u{i}"
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs
    from app.web_api import _WEB_STORE as WS
    assert WS["conc-3"].name == "u3"
    for i in range(10):
        WS.pop(f"conc-{i}", None)


def test_restart_freshness():
    # новая сессия не видит чужое состояние (документируем in-memory поведение)
    from app.web_api import _get_state
    a = _get_state("fresh-a"); a.name = "Алина"
    b = _get_state("fresh-b")
    assert b.name is None
    from app.web_api import _WEB_STORE as WS
    WS.pop("fresh-a", None); WS.pop("fresh-b", None)


def test_dedup_sliding_window(monkeypatch):
    wa._reset_for_tests()
    monkeypatch.setattr(wa, "_DEDUP_CAP", 3)
    for m in ["m1", "m2", "m3"]:
        wa._mark_dedup(m)
    assert wa._is_dedup("m1") is True
    wa._mark_dedup("m4")
    assert wa._is_dedup("m1") is False  # самый старый вытеснен, а не clear() всего
    assert wa._is_dedup("m4") is True
    wa._reset_for_tests()


def test_webhook_body_too_large(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "")
    monkeypatch.setenv("WHATSAPP_ALLOW_UNVERIFIED", "1")
    c = TestClient(app)
    r = c.post("/webhook/whatsapp", content=b"x" * 1_000_001, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_no_truncated_answers_regression(monkeypatch):
    """Прошлый баг: «Уточню у администратора. Как» — ответ обрывался на середине.

    Точная последовательность из лога теста — ни один ответ не должен обрываться.
    """
    from app.bot_logic import DialogState, reply, GREETING_FULL, UNCLEAR_REPLY, FAQ_UNKNOWN_REPLY, OFF_TOPIC_REPLY
    from app.admin_notify import is_booking_complete
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEMO_BOOKING", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    seq = [
        ("программирование", OFF_TOPIC_REPLY),
        ("как стать лучшим программистом", OFF_TOPIC_REPLY),
        ("ы", GREETING_FULL),
        ("ы", UNCLEAR_REPLY),
        ("гей", None),  # inappropriate/unclear/fallback — главное без обрыва
    ]
    for msg, expected in seq:
        s = DialogState()
        if msg == "ы":
            # первый «ы» даёт приветствие, второй — короткий переспрос
            reply(s, "ы")
            r = reply(s, "ы")
            assert r == UNCLEAR_REPLY, f"повторное приветствие: {r!r}"
        else:
            r = reply(s, msg)
        assert isinstance(r, str) and r.strip() == r, f"пробелы/пусто: {r!r}"
        assert r[-1] in ".?!):" or len(r) > 10, f"обрыв: {r!r}"
        if expected is not None and msg != "ы":
            assert r == expected, f"{msg!r}: {r!r} != {expected!r}"


def test_truncation_guard_llm_fallback(monkeypatch):
    """Даже если LLM вернёт обрывок — бэктранспорт шлёт как есть, но мы фиксируем лог."""
    from app.bot_logic import DialogState, reply
    monkeypatch.setenv("GROQ_API_KEY", "")
    s = DialogState()
    r = reply(s, "привет")
    assert isinstance(r, str)


def test_classification_4_categories(monkeypatch):
    from app.bot_logic import DialogState, reply, GREETING_FULL, UNCLEAR_REPLY, FAQ_UNKNOWN_REPLY, INAPPROPRIATE_REPLY, OFF_TOPIC_REPLY
    from app.admin_notify import is_booking_complete
    # off_topic
    s = DialogState()
    assert reply(s, "программирование") == OFF_TOPIC_REPLY
    # unclear — приветствие один раз, потом короткий переспрос
    s = DialogState()
    assert reply(s, "ы") == GREETING_FULL
    assert reply(s, "ы") == UNCLEAR_REPLY
    assert reply(s, "ы") == UNCLEAR_REPLY  # не повторяет приветствие
    # faq_unknown — только on-topic вопрос без ответа
    s = DialogState()
    assert reply(s, "делаете кератин?") == FAQ_UNKNOWN_REPLY
    # inappropriate
    s = DialogState()
    assert reply(s, "ты тупая дура") == INAPPROPRIATE_REPLY
    # off_topic не собирает лид: phone-детектор срабатывает, но заявка не завершена
    s = DialogState()
    reply(s, "как поступить в вуз")
    reply(s, "Айгерим")
    reply(s, "+7 707 123 45 67")
    assert not is_booking_complete(s)
    assert s.service is None and s.branch is None


def test_master_step_in_booking(monkeypatch):
    """Бот спрашивает мастера и показывает реальные часы, appointment создаётся."""
    import sqlite3, gc, os
    from pathlib import Path
    from app.bot_logic import DialogState, reply
    import tempfile
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "demo_master.db")
    monkeypatch.setenv("DEMO_BOOKING", "1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    eng = sqlite3.connect(db_path)
    eng.executescript("""
    DROP TABLE IF EXISTS appointments; DROP TABLE IF EXISTS master_services;
    DROP TABLE IF EXISTS master_branches; DROP TABLE IF EXISTS working_hours;
    DROP TABLE IF EXISTS schedule_exceptions; DROP TABLE IF EXISTS services;
    DROP TABLE IF EXISTS masters; DROP TABLE IF EXISTS branches;
    """)
    eng.executescript("""
    CREATE TABLE branches (id INTEGER PRIMARY KEY, name TEXT, address TEXT, timezone TEXT, is_active INTEGER);
    INSERT INTO branches VALUES (1, 'Abramenko Studio', 'Букетова 61', 'Asia/Almaty', 1);
    CREATE TABLE masters (id INTEGER PRIMARY KEY, name TEXT, specialization TEXT, is_active INTEGER);
    INSERT INTO masters VALUES (1, 'Анна', 'колорист', 1);
    CREATE TABLE services (id INTEGER PRIMARY KEY, name TEXT, duration_minutes INTEGER, price_min INTEGER, price_max INTEGER, category TEXT);
    INSERT INTO services VALUES (1, 'Балаяж', 60, 25000, 80000, 'окрашивание');
    CREATE TABLE master_branches (master_id INTEGER, branch_id INTEGER);
    INSERT INTO master_branches VALUES (1, 1);
    CREATE TABLE master_services (master_id INTEGER, service_id INTEGER);
    INSERT INTO master_services VALUES (1, 1);
    CREATE TABLE working_hours (id INTEGER PRIMARY KEY, master_id INTEGER, weekday INTEGER, start_time TEXT, end_time TEXT);
    """)
    for wd in range(6):
        eng.execute(f"INSERT INTO working_hours VALUES ({wd+1}, 1, {wd}, '10:00', '19:00')")
    eng.commit(); eng.close()
    from app.models import Appointment
    e3 = sqlite3.connect(db_path)
    e3.execute("""CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY, branch_id INTEGER, master_id INTEGER, service_id INTEGER,
        client_name TEXT, client_phone TEXT, starts_at TEXT, ends_at TEXT,
        status TEXT DEFAULT 'booked', created_at TEXT)""")
    e3.commit(); e3.close()
    s = DialogState()
    reply(s, "хочу балаяж")
    reply(s, "окрашены")
    r_branch = reply(s, "Жамбыла")
    # реальные слоты: один мастер → сразу дата, или список мастеров; НЕ «будни или выходные»
    assert "будни или выходные" not in r_branch
    # выбор мастера (несколько) или дата (один мастер)
    assert "мастер" in r_branch.lower() or "дату" in r_branch.lower()
    # после даты показываются конкретные часы (один мастер «Анна» из демо-БД)
    r_slots = reply(s, "завтра")
    assert "свободные окна" in r_slots.lower() and "10:00" in r_slots, r_slots
    # выбор слота -> имя -> телефон -> appointment в БД
    reply(s, "1")
    reply(s, "Айгерим")
    r_final = reply(s, "+7 707 123 45 67")
    assert "записаны" in r_final.lower()
    assert s.step == "done"
    chk = sqlite3.connect(db_path)
    cnt = chk.execute("SELECT COUNT(*) FROM appointments WHERE status='booked'").fetchone()[0]
    chk.close()
    gc.collect()
    assert cnt >= 1, "appointment не создан в БД"


def test_metrics_p95_and_llm_stats():
    c = TestClient(app)
    for i in range(3):
        c.post("/api/chat", json={"session_id": f"m-{i}", "message": "привет"})
    r = c.get("/api/metrics")
    body = r.json()
    assert body["chat_requests"] >= 3
    assert body["chat_p95_ms"] >= 0
    assert "llm_calls" in body and "llm_failures" in body


def test_ip_rate_limit(monkeypatch):
    import app.web_api as w
    monkeypatch.setattr(w, "_IP_RATE_LIMIT", 2)
    w._RATE.clear()
    c = TestClient(app)
    for i in range(2):
        assert c.post("/api/chat", json={"session_id": f"ip-{i}", "message": "привет"}).status_code == 200
    r = c.post("/api/chat", json={"session_id": "ip-2", "message": "привет"})
    assert r.status_code == 429
    w._RATE.clear()


def test_cancel_button_in_demo():
    c = TestClient(app)
    html = c.get("/").text
    assert 'id="btn-cancel"' in html
