import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os


def test_dialog_state_roundtrip():
    from app.bot_logic import DialogState
    s = DialogState()
    s.intent, s.service, s.branch, s.branch_id = "booking", "Балаяж", "Madame", "madame"
    s.master_id, s.master_name = 3, "Анна"
    s.slots = ["2026-09-10T10:00:00+05:00"]
    s.selected_slot, s.name, s.phone = s.slots[0], "Айгерим", "+7 707 123 45 67"
    s.step, s.greeted = "done", True
    s._admin_notified = True
    d = s.to_dict()
    # только JSON-совместимое
    import json
    json.dumps(d, ensure_ascii=False)
    r = DialogState.from_dict(d)
    assert r.intent == "booking" and r.branch_id == "madame"
    assert r.slots == s.slots and r.step == "done" and r.greeted is True
    assert getattr(r, "_admin_notified", False) is True


def test_dialog_state_from_dict_bad_input():
    from app.bot_logic import DialogState
    assert DialogState.from_dict({}).step == "start"
    assert DialogState.from_dict(None).step == "start"
    assert DialogState.from_dict({"step": "hacker", "slots": "notalist"}).step == "start"


def test_persistent_store_memory_fallback():
    os.environ.pop("REDIS_URL", None)
    from app.session_store import PersistentSessionStore
    store = PersistentSessionStore(prefix="test:")
    assert store.backend == "memory"
    st = store.get("u1")
    st.name = "Айгерим"
    store.set("u1", st)
    assert store.get("u1").name == "Айгерим"
    store.reset("u1")
    assert store.get("u1").name is None


def test_persistent_store_bad_redis_falls_back():
    os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"
    try:
        import redis  # noqa
    except ImportError:
        return  # без пакета — get_redis_client вернёт None, тоже fallback
    from app.session_store import PersistentSessionStore
    store = PersistentSessionStore(prefix="test:")
    # Redis недоступен — работаем через память, не падаем
    st = store.get("u9")
    st.step = "await_phone"
    store.set("u9", st)
    assert store.get("u9").step == "await_phone"
    os.environ.pop("REDIS_URL", None)


def test_premium_extra_env():
    os.environ["TG_PREMIUM_EMOJI_EXTRA"] = "💇:1234567890123456789"
    try:
        from importlib import reload
        import app.tg_premium as tp
        reload(tp)
        out = tp.premium("Балаяж 💇 стоит")
        assert "1234567890123456789" in out
        # битые пары не роняют
        os.environ["TG_PREMIUM_EMOJI_EXTRA"] = "без-двоеточия,💇:нецифры"
        reload(tp)
        assert tp.premium("текст") == "текст"
    finally:
        os.environ.pop("TG_PREMIUM_EMOJI_EXTRA", None)
        from importlib import reload
        import app.tg_premium as tp
        reload(tp)


def test_admin_message_only_tabular_emoji():
    import re
    from app.admin_notify import build_admin_message
    from app.bot_logic import DialogState
    from app.tg_premium import EMOJI_IDS, premium
    s = DialogState()
    s.intent, s.service, s.branch, s.name, s.phone = "booking", "Балаяж", "Madame", "А", "+7 707 111 22 33"
    s.time_pref, s.step, s.master_name = "завтра", "done", "Анна"
    s.selected_slot = "2026-09-10T10:00:00+05:00"
    raw = build_admin_message(s, 1, "u")
    # всё, что в карточке — либо табличное, либо ★/текст: premium ничего не должен вычистить молча
    out = premium(raw)
    bare = re.sub(r"<tg-emoji[^>]*>.*?</tg-emoji>", "", out)
    strip_re = re.compile(
        "[\U0001F000-\U0001FAFF\u2600-\u2604\u2606-\u26FF\u2700-\u27BF"
        "\u2B00-\u2BFF\uFE0F\u200d\U0001F1E6-\U0001F1FF]"
    )
    assert not strip_re.search(bare), bare


def test_whatsapp_status_endpoint():
    from fastapi.testclient import TestClient
    from app.web_api import app
    c = TestClient(app)
    r = c.get("/api/whatsapp/status")
    assert r.status_code == 200
    body = r.json()
    assert "configured" in body and "missing" in body
    # секретов наружу нет
    assert "gsk" not in r.text and "AAE" not in r.text
