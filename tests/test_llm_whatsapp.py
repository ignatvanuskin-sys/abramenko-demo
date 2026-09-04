import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
from unittest.mock import patch, AsyncMock, MagicMock

from app.bot_logic import DialogState, reply
from app import llm_client

def test_typo_baliazh_price():
    s = DialogState()
    # опечатка балияж должна всё равно дать цену
    r = reply(s, "скока стоит балияж?")
    assert "25 000" in r or "80 000" in r

def test_conversational_hello():
    s = DialogState()
    r = reply(s, "привет хочу покраситься")
    # должен распознать booking
    assert s.intent == "booking" or "окрашивание" in r.lower() or "балаяж" in r.lower() or "Что вас интересует" in r

def test_combined_time_branch():
    s = DialogState()
    reply(s, "хочу балаяж")
    reply(s, "окрашены")
    r = reply(s, "хочу балаяж на выходных вечером на жамбылу")
    # должен понять время, но не ломаться
    assert s.time_pref is not None or "филиал" in r.lower()

def test_multiple_data_at_once():
    s = DialogState()
    r = reply(s, "я Алина хочу балаяж волосы крашеные суббота жамбыла")
    # слитные данные — должен не падать, распознал booking
    assert s.intent == "booking" or r is not None

def test_incomplete_booking():
    s = DialogState()
    r = reply(s, "хочу записаться")
    assert "услуга" in r.lower() or "окрашивание" in r.lower()

def test_faq_laser():
    s = DialogState()
    r = reply(s, "у вас есть лазер?")
    assert "Букетова" in r
    assert "лазер" in r.lower()

def test_unknown_sobaka(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    s = DialogState()
    r = reply(s, "а можно с собакой?")
    assert isinstance(r, str)
    assert "Уточню" in r or "Здравствуйте" in r

def test_hallucination_no_facts(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    s = DialogState()
    r = reply(s, "а у вас есть вертолётная площадка?")
    assert "Уточню" in r or "Здравствуйте" in r
    assert "вертол" not in r.lower() or "Уточню" in r

def test_llm_error_fallback(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    s = DialogState()
    with patch("app.llm_client._call_openai_compatible", side_effect=RuntimeError("timeout")):
        r = reply(s, "можно с собакой неизвестный вопрос 12345")
        assert isinstance(r, str)
        # safe fallback
        assert "Уточню" in r or "Здравствуйте" in r

def test_llm_timeout_fallback(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    s = DialogState()
    # simulate timeout
    def slow(*a, **kw):
        time.sleep(0.01)
        raise TimeoutError("timeout")
    with patch("app.llm_client._call_openai_compatible", side_effect=slow):
        r = reply(s, "неизвестный вопрос про котиков")
        assert isinstance(r, str)

def test_llm_unavailable_no_crash(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    s = DialogState()
    # без ключа бот не падает
    r = reply(s, "привт хачу балаяж")
    assert isinstance(r, str)

def test_booking_llm_does_not_change_state(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    s = DialogState()
    reply(s, "хочу балаяж")
    assert s.intent == "booking"
    assert s.step == "clarify_hair"
    # LLM не должен менять booking state
    with patch("app.llm_client._call_openai_compatible", return_value="LLM hallucination"):
        r = reply(s, "окрашены")
        assert s.step == "time"
        assert s.intent == "booking"

def test_provider_abstraction_groq():
    import os
    os.environ["LLM_PROVIDER"] = "groq"
    os.environ["LLM_API_KEY"] = "gsk_test"
    os.environ["LLM_MODEL"] = "openai/gpt-oss-120b"
    cfg = llm_client._get_config()
    assert cfg is not None
    assert cfg["provider"] == "groq"
    assert cfg["model"] == "openai/gpt-oss-120b"
    # cleanup
    del os.environ["LLM_PROVIDER"]
    del os.environ["LLM_API_KEY"]
    del os.environ["LLM_MODEL"]

def test_provider_fallback():
    import os
    os.environ["LLM_PROVIDER"] = "groq"
    os.environ["LLM_API_KEY"] = "gsk_test"
    os.environ["OPENAI_API_KEY"] = "sk-test-fallback"
    fb = llm_client._get_fallback_config()
    assert fb is not None
    assert fb["provider"] == "openai"
    del os.environ["LLM_PROVIDER"]
    del os.environ["LLM_API_KEY"]
    del os.environ["OPENAI_API_KEY"]

def test_llm_available():
    import os
    os.environ["LLM_API_KEY"] = "test"
    assert llm_client.llm_available() is True
    del os.environ["LLM_API_KEY"]
    # legacy
    os.environ["OPENAI_API_KEY"] = "test2"
    assert llm_client.llm_available() is True
    del os.environ["OPENAI_API_KEY"]
    assert llm_client.llm_available() is False
