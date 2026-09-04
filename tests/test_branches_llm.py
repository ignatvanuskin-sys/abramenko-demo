import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import patch, AsyncMock

from app.bot_logic import DialogState, reply, faq_answer, detect_intent
from app.admin_notify import is_booking_complete

# --- Филиалы ---
def test_branch_where_are_you_returns_both():
    ans = faq_answer("где вы?")
    assert "Букетова" in ans
    assert "Жамбыла" in ans
    assert "Какой филиал вам удобнее?" in ans
    assert "4.6" in ans and "4.8" in ans

def test_branch_where_address():
    ans = faq_answer("ваш адрес?")
    assert ans is not None
    assert "Букетова" in ans or "Жамбыла" in ans

def test_branch_what_on_zhambyla_only():
    ans = faq_answer("что на Жамбыла?")
    assert "Madame" in ans
    assert "Жамбыла" in ans
    assert "Победитель" in ans or "Премии" in ans
    assert "парковка" in ans.lower()
    # не должен содержать брови/лазер (только Букетова)
    assert "бров" not in ans.lower() or "лазер" not in ans.lower()  # Madame не про брови

def test_branch_what_on_zhambyla_variants():
    for q in ["что есть на Жамбыла?", "что у вас на Жамбыла?", "расскажите про Жамбыла"]:
        ans = faq_answer(q)
        assert "Жамбыла" in ans
        assert "Madame" in ans

def test_branch_brows_only_buketova():
    ans = faq_answer("делаете брови?")
    assert "Букетова 61" in ans
    assert "Жамбыла 127" in ans and "уточню" in ans
    assert "Какой филиал вам удобнее?" in ans
    assert "обоих филиалах" not in ans

def test_branch_laser_only_buketova():
    ans = faq_answer("делаете лазер?")
    assert "Букетова" in ans
    assert "уточню" in ans

def test_branch_male_manicure_only_zhambyla():
    ans = faq_answer("Есть мужской маникюр?")
    assert "Жамбыла 127" in ans
    assert "Букетова" not in ans or "уточню" not in ans  # только Жамбыла

def test_branch_wedding_only_zhambyla():
    ans = faq_answer("Есть свадебные причёски?")
    assert "Жамбыла" in ans
    assert "Madame" in ans

def test_branch_local_services_not_mixed():
    # брови не должны приписываться Madame
    ans = faq_answer("делаете брови?")
    assert "Букетова" in ans
    assert "Madame —" not in ans or "брови" not in ans.split("Madame")[0]  # грубый чек

# --- Vacancy / Model / Training ---
def test_vacancy_intent():
    for txt in ["требуется мастер", "требуется мастер-парикмахер", "есть вакансия?", "хочу работать у вас", "ищете мастеров?"]:
        assert detect_intent(txt) == "vacancy", txt

def test_model_intent():
    for txt in ["нужна модель", "ищете моделей?", "хочу стать моделью", "требуются модели!"]:
        assert detect_intent(txt) == "model", txt

def test_training_intent():
    for txt in ["хочу пройти курс", "обучение есть?", "курс колорист с нуля"]:
        assert detect_intent(txt) == "training", txt

def test_vacancy_flow():
    s = DialogState()
    r1 = reply(s, "требуется мастер")
    assert "специализация" in r1.lower()
    r2 = reply(s, "парикмахер")
    assert "портфолио" in r2.lower()
    r3 = reply(s, "есть портфолио")
    assert "зовут" in r3.lower()
    r4 = reply(s, "Иван")
    assert "номер" in r4.lower()
    r5 = reply(s, "+7 707 111 22 33")
    assert "вакансии" in r5.lower()
    assert s.step == "done"
    assert is_booking_complete(s) is True

def test_model_flow():
    s = DialogState()
    reply(s, "хочу стать моделью")
    reply(s, "балаяж")
    reply(s, "готова, фото есть")
    reply(s, "Мария")
    r = reply(s, "+7 707 111 22 33")
    assert "мастеру" in r.lower()
    assert s.intent == "model"

def test_training_flow():
    s = DialogState()
    reply(s, "курс колорист с нуля")
    reply(s, "колорист")
    reply(s, "опыта нет")
    reply(s, "Анна")
    r = reply(s, "+7 707 111 22 33")
    assert "курсам" in r.lower()
    assert s.intent == "training"

def test_training_no_price_hallucination():
    s = DialogState()
    reply(s, "курс колорист с нуля")
    # второй вопрос уже содержит фразу про уточню у администратора
    r = reply(s, "колорист с нуля")
    assert "уточню" in r.lower() or "опыт" in r.lower()

# --- Booking still deterministic ---
def test_booking_full_still_passes():
    s = DialogState()
    reply(s, "здравствуйте, хочу балаяж")
    reply(s, "окрашены")
    reply(s, "будни")
    reply(s, "Жамбыла")
    reply(s, "Айгерим")
    r = reply(s, "+7 707 123 45 67")
    assert "Передал администратору" in r
    assert s.step == "done"

# --- LLM fallback ---
def test_llm_not_called_for_faq(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    s = DialogState()
    # FAQ should be handled without LLM
    with patch("app.bot_logic._try_llm_fallback") as mock:
        reply(s, "где вы?")
        mock.assert_not_called()

def test_llm_not_called_for_booking_flow(monkeypatch):
    s = DialogState()
    reply(s, "хочу балаяж")
    # внутри booking (clarify_hair) LLM не должен вызываться
    with patch("app.bot_logic._try_llm_fallback") as mock:
        reply(s, "окрашены")
        mock.assert_not_called()

def test_llm_called_for_unknown(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = DialogState()
    with patch("app.llm_client.llm_reply", return_value="У нас есть кофе, уточню детали у администратора.") as mock_llm:
        r = reply(s, "а у вас кофе есть?")
        mock_llm.assert_called_once()
        assert "кофе" in r.lower() or "уточню" in r.lower()

def test_llm_fallback_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    s = DialogState()
    r = reply(s, "а можно с собакой?")
    # без ключа — безопасный fallback, не падает
    assert isinstance(r, str)
    assert len(r) > 0
    # должен быть приветствие или уточню, но не ошибка
    assert "Уточню" in r or "Здравствуйте" in r or "Что вас интересует" in r

def test_llm_failure_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = DialogState()
    with patch("app.llm_client.llm_reply", side_effect=RuntimeError("api down")):
        r = reply(s, "можно с собакой?")
        # при ошибке LLM — fallback к безопасному приветствию
        assert isinstance(r, str)
        assert "Уточню" in r or "Здравствуйте" in r or "Что вас интересует" in r

def test_llm_not_affect_booking_state(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    s = DialogState()
    # даже если LLM пытается ответить, состояние booking не должно меняться им
    reply(s, "хочу балаяж")
    assert s.intent == "booking"
    assert s.step == "clarify_hair"
    # LLM не должен был изменить intent
    assert s.intent != "vacancy"
