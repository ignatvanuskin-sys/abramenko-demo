import hmac, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from app.web_api import app
from app import whatsapp as wa

def _sig(secret, body: bytes):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

def _wa_payload(wa_id="77001234567", mid="wamid.test123", text="привет"):
    return {
        "entry": [{"changes": [{"value": {"messages": [{"from": wa_id, "id": mid, "type": "text", "text": {"body": text}}], "contacts": [{"wa_id": wa_id}]}}]}]
    }

# 1-3 verification
def test_verify_ok(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
    c = TestClient(app)
    r = c.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "tok123", "hub.challenge": "CHAL"})
    assert r.status_code == 200 and r.text == "CHAL"

def test_verify_bad_token(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
    c = TestClient(app)
    r = c.get("/webhook/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "bad", "hub.challenge": "CHAL"})
    assert r.status_code == 403

def test_verify_bad_mode(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "tok123")
    c = TestClient(app)
    r = c.get("/webhook/whatsapp", params={"hub.mode": "unsubscribe", "hub.verify_token": "tok123", "hub.challenge": "CHAL"})
    assert r.status_code == 403

# 4-6 signature
def test_sig_valid(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "secret123")
    body = json.dumps(_wa_payload()).encode()
    sig = _sig("secret123", body)
    assert wa.verify_signature(body, sig) is True

def test_sig_invalid(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "secret123")
    body = json.dumps(_wa_payload()).encode()
    assert wa.verify_signature(body, "sha256=bad") is False

def test_sig_missing(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "secret123")
    body = json.dumps(_wa_payload()).encode()
    assert wa.verify_signature(body, None) is False
    assert wa.verify_signature(body, "") is False

# 7-9 parsing
def test_parse_valid():
    p = _wa_payload(wa_id="77001", mid="mid1", text="хочу балаяж")
    res = wa._parse_whatsapp_message(p)
    assert res == {"wa_id": "77001", "message_id": "mid1", "text": "хочу балаяж"}

def test_parse_malformed():
    assert wa._parse_whatsapp_message({}) is None
    assert wa._parse_whatsapp_message({"entry": []}) is None

def test_parse_non_text():
    p = {"entry": [{"changes": [{"value": {"messages": [{"from": "1", "id": "mid", "type": "image", "image": {"id": "123"}}]}}]}]}
    assert wa._parse_whatsapp_message(p) is None

# 10-11 session
def test_session_isolation():
    wa._reset_for_tests()
    s1 = wa._get_state("111")
    s2 = wa._get_state("222")
    assert s1 is not s2
    s1.name = "A"
    assert s2.name is None

def test_session_persists():
    wa._reset_for_tests()
    s = wa._get_state("111")
    s.name = "Bob"
    assert wa._get_state("111").name == "Bob"

# 12 dedup
def test_dedup():
    wa._reset_for_tests()
    assert wa._is_dedup("mid1") is False
    wa._mark_dedup("mid1")
    assert wa._is_dedup("mid1") is True

# 13-14 bot integration
def test_whatsapp_calls_reply(monkeypatch):
    wa._reset_for_tests()
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "")
    monkeypatch.setenv("WHATSAPP_ALLOW_UNVERIFIED", "1")
    monkeypatch.setenv("WHATSAPP_TOKEN", "")
    # ensure clean state
    c = TestClient(app)
    payload = _wa_payload(wa_id="77002", mid="mid2", text="хочу балаяж")
    body = json.dumps(payload).encode()
    # no signature when secret empty → pass
    with patch("app.whatsapp._send_whatsapp_message", new=AsyncMock()) as mock_send:
        r = c.post("/webhook/whatsapp", content=body, headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        # background task may not have run yet in TestClient, call directly
        import asyncio
        asyncio.run(wa._process_whatsapp_message("77002", "mid2", "хочу балаяж"))
        # state should be booking
        assert wa._get_state("77002").intent == "booking"

def test_booking_not_changed(monkeypatch):
    wa._reset_for_tests()
    import asyncio
    asyncio.run(wa._process_whatsapp_message("77003", "mid3", "хочу балаяж"))
    s = wa._get_state("77003")
    assert s.intent == "booking"
    assert s.step == "clarify_hair"

# 15-17 meta send
def test_meta_request_formation(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "tok123")
    monkeypatch.setenv("PHONE_NUMBER_ID", "12345")
    monkeypatch.setenv("GRAPH_API_VERSION", "v21.0")
    with patch("httpx.AsyncClient") as MockClient:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value.post.return_value = mock_resp
        MockClient.return_value = mock_client
        import asyncio
        asyncio.run(wa._send_whatsapp_message("77001", "hello"))
        # check url and headers
        args, kwargs = mock_client.__aenter__.return_value.post.call_args
        url = args[0]
        assert "12345/messages" in url
        assert "v21.0" in url
        headers = kwargs["headers"]
        assert "Bearer tok123" in headers["Authorization"]
        # token not in json body
        assert "tok123" not in str(kwargs["json"])

def test_token_not_in_logs(monkeypatch, caplog):
    monkeypatch.setenv("WHATSAPP_TOKEN", "supersecrettoken123")
    monkeypatch.setenv("PHONE_NUMBER_ID", "12345")
    with patch("httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_client.__aenter__.return_value.post.return_value = mock_resp
        MockClient.return_value = mock_client
        import asyncio, logging
        with caplog.at_level(logging.WARNING):
            asyncio.run(wa._send_whatsapp_message("77001", "hi"))
        # logs should not contain token
        assert "supersecrettoken123" not in caplog.text

def test_timeout_429_5xx(monkeypatch):
    monkeypatch.setenv("WHATSAPP_TOKEN", "tok")
    monkeypatch.setenv("PHONE_NUMBER_ID", "123")
    import httpx
    for status in [429, 500, 200]:
        with patch("httpx.AsyncClient") as MockClient:
            mock_resp = AsyncMock()
            mock_resp.status_code = status
            mock_resp.text = "error body"
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value.post.return_value = mock_resp
            MockClient.return_value = mock_client
            import asyncio
            # should not raise
            asyncio.run(wa._send_whatsapp_message("77001", "hi"))

def test_webhook_malformed_no_crash(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "")
    monkeypatch.setenv("WHATSAPP_ALLOW_UNVERIFIED", "1")
    c = TestClient(app)
    r = c.post("/webhook/whatsapp", json={"bad": "data"})
    assert r.status_code == 200

def test_webhook_non_text_no_crash(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "")
    monkeypatch.setenv("WHATSAPP_ALLOW_UNVERIFIED", "1")
    c = TestClient(app)
    payload = {"entry": [{"changes": [{"value": {"messages": [{"from": "1", "id": "mid", "type": "image"}]}}]}]}
    r = c.post("/webhook/whatsapp", json=payload)
    assert r.status_code == 200

def test_post_requires_signature_when_secret_set(monkeypatch):
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "secret123")
    c = TestClient(app)
    payload = _wa_payload()
    r = c.post("/webhook/whatsapp", json=payload)  # no signature header
    assert r.status_code == 403

def test_dedup_not_processed_twice(monkeypatch):
    wa._reset_for_tests()
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "")
    with patch("app.whatsapp._send_whatsapp_message", new=AsyncMock()) as mock_send:
        import asyncio
        asyncio.run(wa._process_whatsapp_message("77004", "mid_dup", "привет"))
        asyncio.run(wa._process_whatsapp_message("77004", "mid_dup", "привет"))
        # second dedup skip, only one send
        assert mock_send.call_count == 1
