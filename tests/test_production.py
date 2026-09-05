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
