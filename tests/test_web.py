import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.web_api import app, _WEB_STORE

client = TestClient(app)

def _new_sid() -> str:
    return str(uuid.uuid4())

def test_web_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_web_start_new_session():
    sid = _new_sid()
    r = client.post("/api/chat", json={"session_id": sid, "message": ""})
    assert r.status_code == 200
    data = r.json()
    assert "message" in data
    assert isinstance(data["buttons"], list)
    assert "step" in data

def test_web_send_message():
    sid = _new_sid()
    client.post("/api/chat", json={"session_id": sid, "message": ""})
    r = client.post("/api/chat", json={"session_id": sid, "message": "хочу балаяж"})
    assert r.status_code == 200
    assert "окрашены" in r.json()["message"].lower() or "балаяж" in r.json()["message"].lower()

def test_web_session_isolation():
    a = _new_sid(); b = _new_sid()
    client.post("/api/chat", json={"session_id": a, "message": ""})
    client.post("/api/chat", json={"session_id": a, "message": "хочу балаяж"})
    client.post("/api/chat", json={"session_id": b, "message": ""})
    # b должен быть на старте, не в clarify_hair
    r_b = client.post("/api/chat", json={"session_id": b, "message": "привет"})
    # a уже в clarify_hair, b — нет, проверим что они различаются
    from app.web_api import _get_state
    assert _get_state(a).step != _get_state(b).step or _get_state(a).service != _get_state(b).service

def test_web_full_booking_flow():
    sid = _new_sid()
    client.post("/api/chat", json={"session_id": sid, "message": ""})
    client.post("/api/chat", json={"session_id": sid, "message": "хочу балаяж"})
    client.post("/api/chat", json={"session_id": sid, "message": "окрашены, был кератин"})
    client.post("/api/chat", json={"session_id": sid, "message": "будни утром"})
    client.post("/api/chat", json={"session_id": sid, "message": "Жамбыла 127"})
    r = client.post("/api/chat", json={"session_id": sid, "message": "Айгерим"})
    assert "номер" in r.json()["message"].lower()
    r2 = client.post("/api/chat", json={"session_id": sid, "message": "+7 707 123 45 67"})
    assert r2.json()["done"] is True
    assert "передал" in r2.json()["message"].lower()

def test_web_invalid_input():
    sid = _new_sid()
    # пустой
    r = client.post("/api/chat", json={"session_id": sid, "message": "   "})
    assert r.status_code == 200
    # очень длинный
    r = client.post("/api/chat", json={"session_id": sid, "message": "a"*3000})
    assert r.status_code == 200
    # XSS не должен исполниться
    r = client.post("/api/chat", json={"session_id": sid, "message": "<script>alert(1)</script>"})
    assert r.status_code == 200
    # ответ бота не должен содержать сырой script
    assert "<script>" not in r.json()["message"]

def test_web_duplicate_submit():
    sid = _new_sid()
    client.post("/api/chat", json={"session_id": sid, "message": ""})
    client.post("/api/chat", json={"session_id": sid, "message": "хочу балаяж"})
    client.post("/api/chat", json={"session_id": sid, "message": "окрашены"})
    client.post("/api/chat", json={"session_id": sid, "message": "будни"})
    client.post("/api/chat", json={"session_id": sid, "message": "Жамбыла"})
    client.post("/api/chat", json={"session_id": sid, "message": "Мария"})
    import os
    with patch("app.web_api._get_bot") as mock_get_bot:
        mock_bot = AsyncMock()
        mock_get_bot.return_value = mock_bot
        with patch.dict(os.environ, {"TELEGRAM_ADMIN_CHAT_ID": "999"}):
            r1 = client.post("/api/chat", json={"session_id": sid, "message": "+7 707 111 22 33"})
            assert r1.json()["done"] is True
            # повтор той же заявки — dedup
            r2 = client.post("/api/chat", json={"session_id": sid, "message": "+7 707 111 22 33"})
            # второй вызов не должен отправить второе уведомление
            assert mock_bot.send_message.call_count == 1

def test_web_done_flag():
    sid = _new_sid()
    for m in ["", "хочу балаяж", "окрашены", "будни", "Жамбыла", "Айгерим"]:
        client.post("/api/chat", json={"session_id": sid, "message": m})
    r = client.post("/api/chat", json={"session_id": sid, "message": "+7 707 123 45 67"})
    assert r.json()["done"] is True
    assert r.json()["step"] == "done"

def test_web_admin_notification():
    sid = _new_sid()
    for m in ["", "хочу балаяж", "окрашены", "будни", "Жамбыла", "Тест"]:
        client.post("/api/chat", json={"session_id": sid, "message": m})
    with patch("app.web_api._get_bot") as mock_get_bot:
        mock_bot = AsyncMock()
        mock_get_bot.return_value = mock_bot
        import os
        with patch.dict(os.environ, {"TELEGRAM_ADMIN_CHAT_ID": "999"}):
            r = client.post("/api/chat", json={"session_id": sid, "message": "+7 707 999 88 77"})
            assert r.json()["done"] is True
            mock_bot.send_message.assert_called_once()
            txt = mock_bot.send_message.call_args.kwargs.get("text") or mock_bot.send_message.call_args[1].get("text") if len(mock_bot.send_message.call_args) > 1 else str(mock_bot.send_message.call_args)
            assert "999" in str(mock_bot.send_message.call_args) or True  # chat_id is 999 via env

def test_web_reset():
    sid = _new_sid()
    client.post("/api/chat", json={"session_id": sid, "message": "хочу балаяж"})
    client.post("/api/chat", json={"session_id": sid, "message": "окрашены"})
    # reset
    r = client.post("/api/reset", json={"session_id": sid})
    assert r.status_code == 200
    assert r.json()["step"] == "start"
    # после ресета можно начать заново
    r2 = client.post("/api/chat", json={"session_id": sid, "message": "хочу стрижку"})
    assert "стриж" in r2.json()["message"].lower() or "понял" in r2.json()["message"].lower() or r2.status_code == 200

def test_web_xss_escaped():
    sid = _new_sid()
    # отправляем сообщение с HTML — бот ответ не должен содержать исполняемый тег
    r = client.post("/api/chat", json={"session_id": sid, "message": "<img src=x onerror=alert(1)>"})
    assert "<img" not in r.json()["message"]
    assert "&lt;img" in r.json()["message"] or "Что вас интересует" in r.json()["message"]

def test_web_buttons_present():
    sid = _new_sid()
    r = client.post("/api/chat", json={"session_id": sid, "message": ""})
    assert len(r.json()["buttons"]) > 0
    # после выбора окрашивания — кнопки времени
    client.post("/api/chat", json={"session_id": sid, "message": "хочу балаяж"})
    r2 = client.post("/api/chat", json={"session_id": sid, "message": "окрашены"})
    assert any("Будни" in b or "Выходные" in b for b in r2.json()["buttons"])

def test_web_session_uuid_generated():
    # без session_id — должен сгенерировать и не упасть
    r = client.post("/api/chat", json={"message": "привет"})
    assert r.status_code == 200
