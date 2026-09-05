import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import patch
from app.bot_logic import DialogState, reply, is_off_topic
from app.admin_notify import is_booking_complete

def test_off_topic_vuz():
    s = DialogState()
    r = reply(s, "как поступить в вуз")
    assert "подскажу только по услугам Abramenko Studio" in r
    assert s.intent is None
    assert s.step == "start"
    assert not is_booking_complete(s)

def test_off_topic_university():
    s = DialogState()
    r = reply(s, "как поступить в университет")
    assert "подскажу только по услугам" in r
    assert s.step == "start"

def test_off_topic_python():
    s = DialogState()
    r = reply(s, "расскажи про Python")
    assert "подскажу только по услугам" in r

def test_off_topic_english():
    s = DialogState()
    r = reply(s, "как выучить английский")
    assert "подскажу только по услугам" in r

def test_off_topic_programming_course():
    s = DialogState()
    r = reply(s, "хочу курсы по программированию")
    # должен быть отклонён как нерелевантный training, не как booking
    assert "не проводится" in r.lower()
    assert s.step == "start"
    assert not is_booking_complete(s)

def test_generic_training_still_on_topic():
    s = DialogState()
    r = reply(s, "хочу купить курсы")
    assert "направление" in r.lower()
    assert s.intent == "training"

def test_relevant_training_still_on_topic():
    s = DialogState()
    r = reply(s, "хочу обучение по окрашиванию")
    assert s.intent == "training"
    assert "направление" in r.lower() or "опыт" in r.lower()
    # продолжить с релевантным
    r2 = reply(s, "колорист")
    assert "не проводится" not in r2.lower()

def test_booking_still_booking():
    s = DialogState()
    r = reply(s, "хочу балаяж")
    assert s.intent == "booking"

def test_booking_model_vacancy():
    for txt, exp in [("хочу моделью на брови", "model"), ("ищу работу парикмахером", "vacancy"), ("сколько стоит балаяж?", None), ("где вы находитесь?", None)]:
        s = DialogState()
        reply(s, txt)
        if exp:
            assert s.intent == exp, txt

def test_faq_still_on_topic():
    s = DialogState()
    r = reply(s, "где вы находитесь?")
    assert "Букетова" in r
    assert s.step == "start"  # FAQ не меняет state на booking

def test_local_faq():
    s = DialogState()
    r = reply(s, "на Жамбыла есть брови?")
    # брови только на Букетова, поэтому должен упомянуть Букетова или уточню
    assert "Букетова" in r or "уточню" in r.lower() or "Madame" in r

def test_off_topic_does_not_create_lead():
    s = DialogState()
    reply(s, "как поступить в вуз")
    # попробуем дать телефон — не должен собраться лид
    r = reply(s, "+7 707 123 45 67")
    assert not is_booking_complete(s)
    assert s.step != "done"

def test_off_topic_via_llm_mock():
    s = DialogState()
    with patch("app.bot_logic._is_off_topic_llm", return_value=True):
        r = reply(s, "неоднозначный оффтоп без ключевых слов бла бла")
        assert "подскажу только по услугам" in r

def test_on_topic_via_llm_mock():
    s = DialogState()
    with patch("app.bot_logic._is_off_topic_llm", return_value=False):
        # неоднозначное но LLM говорит on_topic
        r = reply(s, "неоднозначный но про салон бла бла")
        # не должен быть off_topic redirect
        assert "подскажу только по услугам" not in r

def test_free_text_still_on_topic():
    for txt in ["подскажите, пожалуйста, как поступить в университет", "можете рассказать про Python", "а сколько стоит обучение на программиста"]:
        s = DialogState()
        r = reply(s, txt)
        # все эти должны быть off_topic или irrelevant training, но не booking
        assert s.intent is None or s.intent == "training"
        assert "не проводится" in r.lower() or "подскажу только по услугам" in r.lower() or "уточню" in r.lower()

def test_booking_free_text():
    s = DialogState()
    r = reply(s, "можно ли у вас научиться окрашиванию")
    assert s.intent == "training" or s.intent == "booking" or "окраши" in r.lower()

def test_session_isolation_off_topic():
    s1 = DialogState()
    s2 = DialogState()
    reply(s1, "как поступить в вуз")
    reply(s2, "хочу балаяж")
    assert s1.intent is None
    assert s2.intent == "booking"
    assert s1.step == "start"
    assert s2.step == "clarify_hair"
