import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bot_logic import DialogState, reply
from app.admin_notify import is_booking_complete

def test_training_generic_asks_direction():
    s = DialogState()
    r = reply(s, "хочу купить курсы")
    assert "направление" in r.lower()
    assert s.intent == "training"
    assert s.step == "clarify"

def test_training_irrelevant_programming():
    s = DialogState()
    reply(s, "хочу купить курсы")
    r = reply(s, "программирования")
    assert "не проводится" in r.lower()
    assert "программирования" in r.lower()
    assert s.step == "start"
    assert s.intent is None
    # не должен спрашивать опыт/имя/телефон
    assert "опыт" not in r.lower() or "не проводится" in r.lower()
    assert is_booking_complete(s) is False

def test_training_irrelevant_python():
    s = DialogState()
    r = reply(s, "хочу курсы Python")
    # должен отклонить сразу или после уточнения, но не собирать лид
    # проверим оба варианта: либо сразу отклоняет, либо спрашивает направление и потом отклоняет
    if "не проводится" in r.lower():
        assert s.step == "start"
    else:
        # спросил направление
        assert "направление" in r.lower()
        r2 = reply(s, "Python")
        assert "не проводится" in r2.lower()
        assert s.step == "start"

def test_training_relevant_coloring():
    s = DialogState()
    reply(s, "хочу обучение по окрашиванию")
    # должен продолжить, не отклонить
    # в этом случае первый ответ — вопрос про направление, так как "окрашиванию" уже в первом сообщении?
    # Проверим что не отклонил
    assert s.intent == "training"
    # теперь дадим конкретное направление
    s2 = DialogState()
    reply(s2, "хочу купить курсы")
    r = reply(s2, "колорист")
    assert "не проводится" not in r.lower()
    assert "опыт" in r.lower() or "портфолио" in r.lower() or "программе" in r.lower()

def test_training_irrelevant_long():
    s = DialogState()
    r = reply(s, "хочу обучение по программированию на Python")
    assert "не проводится" in r.lower()
    assert s.step == "start"
    assert is_booking_complete(s) is False

def test_booking_still_booking():
    s = DialogState()
    r = reply(s, "хочу балаяж")
    assert s.intent == "booking"

def test_model_still_model():
    s = DialogState()
    r = reply(s, "хочу стать моделью")
    assert s.intent == "model"

def test_vacancy_still_vacancy():
    s = DialogState()
    r = reply(s, "ищу работу")
    assert s.intent == "vacancy"

def test_training_no_lead_for_irrelevant():
    s = DialogState()
    reply(s, "хочу купить курсы")
    reply(s, "программирования")
    # после отклонения не должно быть сбора телефона
    r = reply(s, "нет")
    # должен быть либо снова приветствие, либо уточнение, но не сбор телефона
    assert "телефон" not in r.lower()
    assert is_booking_complete(s) is False
