"""Rule-based логика strictly по промпту: ответ + ровно один вопрос.

Ветки: booking / model / vacancy / training / faq.
Имя и телефон — только в конце. Календаря нет — окна не называем.
"""
import re
from .config import BRANCHES, PRICES, SALON, UNKNOWN_ANSWER

PHONE_RE = re.compile(r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")


class DialogState:
    def __init__(self):
        self.intent = None  # booking|model|vacancy|training
        self.service = None
        self.hair = None
        self.time_pref = None
        self.branch = None
        self.name = None
        self.phone = None
        self.step = "start"


def _find_price(text: str):
    t = text.lower()
    for key, val in PRICES.items():
        if key in t:
            return val
    if "окрашиван" in t or "airtouch" in t or "балаяж" in t or "мелирован" in t or "блонд" in t:
        return "Балаяж / AirTouch / мелирование — 25 000–80 000 ₸, точную сумму назовут на консультации"
    if "стрижк" in t:
        return f"{PRICES['женская стрижка']}, {PRICES['мужская стрижка']}"
    return None


def faq_answer(text: str):
    """Возвращает ответ на частый вопрос или None."""
    t = text.lower()
    if any(w in t for w in ["где", "адрес", "находитесь", "филиал", "жамбыла", "букетова"]):
        b1, b2 = BRANCHES
        return (
            f"Два филиала: {b1['label']} — {b1['address']} ({b1['landmark']}) "
            f"и {b2['label']} — {b2['address']} ({b2['landmark']}). Какой удобнее?"
        )
    if "парков" in t:
        return "На Жамбыла в 2ГИС указана бесплатная парковка на 7 мест. Детали подскажет администратор при звонке."
    if "карт" in t or "оплат" in t or "каспи" in t:
        return "Да, принимаем карту, наличные и перевод с карты."
    if "wi-fi" in t or "wifi" in t or "вай" in t or "вайфай" in t:
        return "Да, для клиентов Wi-Fi есть."
    if "отзыв" in t or "рейтинг" in t or "хорош" in t:
        return "У Madame 4.8 в 2ГИС (191 оценка / 163 отзыва) + премия «Лучший салон красоты 2025», на Букетова 4.6 (170 оценок / 123 отзыва)."
    if "записаться" in t or "как записать" in t:
        return f"Через WhatsApp {SALON['whatsapp_main']} или Instagram {SALON['instagram']} — сейчас этим и занимаемся."
    if "свадеб" in t or "вечерн" in t and "прич" in t:
        return "В Madame указаны свадебные и вечерние причёски. Уточните дату — передам как срочное."
    if any(w in t for w in ["маникюр", "педикюр", "гель-лак", "гель лак", "ногт"]):
        return "В Madame указаны гель-лак, аппаратный маникюр, наращивание гелем, мужской маникюр/педикюр. Цену скажет администратор после консультации."
    if "бров" in t or "эпиляц" in t or "лазер" in t:
        return "Брови и лазерная эпиляция указаны у филиала на Букетова. Про Жамбыла уточню — администратор перезвонит."
    if "цен" in t or "стоим" in t or "сколько" in t or "прайс" in t:
        price = _find_price(text)
        if price:
            return f"{price}. Точная сумма зависит от длины и состояния волос, её назовут на консультации."
        return UNKNOWN_ANSWER
    if "наращиван" in t or "химзавив" in t or "ботокс" in t or "холодное" in t:
        return "Да, делаем. Точную цену скажет мастер после консультации — зависит от исходных волос."
    if "модел" in t:
        return None  # уйдёт в ветку модели
    return None


CLOSINGS = {
    "booking": "Передал администратору, перезвонят и подберут время.",
    "model": "Передал мастеру. Если процедура подойдёт — вам напишут и согласуют время.",
    "vacancy": "Контакт передал, по вакансии с вами свяжутся.",
    "training": "Передал по курсам, вам ответят с расписанием и стоимостью.",
}


def detect_intent(text: str):
    t = text.lower()
    if any(w in t for w in ["ваканс", "работ", "мастером", "трудоустр"]):
        return "vacancy"
    if "модел" in t:
        return "model"
    if any(w in t for w in ["обуч", "курс", "научить"]):
        return "training"
    if any(w in t for w in ["запис", "хочу", "окраш", "стриж", "балаяж", "ногт", "маникюр", "эпиляц", "бров", "свадеб", "цен", "стоим", "филиал", "где"]):
        return "booking"
    return None


def _is_coloring(text_low: str) -> bool:
    return any(w in text_low for w in ["окраш", "балаяж", "блонд", "мелир", "airtouch", "шатуш", "контуринг", "dim-out", "dim out", "total blond"])


def _looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    if "?" in text:
        return True
    return t.startswith(("сколько", "где ", "где?", "как ", "можно", "есть", "делаете", "какая", "какие", "что ", "подскажите", "а "))


def reply(state: DialogState, user_text: str) -> str:
    text = (user_text or "").strip()
    low = text.lower()

    # 0. Телефон ловим в любом месте
    m = PHONE_RE.search(text)
    if m and not state.phone:
        state.phone = m.group(0)
        if state.name and state.intent:
            closing = CLOSINGS.get(state.intent, CLOSINGS["booking"])
            state.step = "done"
            return f"Принял, {state.name}. {closing}"
        if state.step == "await_phone":
            name = state.name or ""
            state.step = "done"
            return f"Принял, {name}. {CLOSINGS.get(state.intent or 'booking', CLOSINGS['booking'])}"

    # 1. FAQ — только если это похоже на вопрос, и не перебиваем слоты время/филиал/имя/телефон
    if state.step in ("time", "branch", "await_name", "await_phone", "clarify_hair"):
        fa = faq_answer(text) if _looks_like_question(text) else None
        if fa:
            follow = _follow_question(state)
            return f"{fa} {follow}" if follow else fa
        # иначе считаем текст значением слота — идём дальше
    else:
        fa = faq_answer(text) if len(low) > 2 else None
        if fa and state.intent != "model" and _looks_like_question(text):
            # на старте фиксируем намерение, чтобы не топтаться
            if state.step == "start":
                state.intent = detect_intent(text) or "booking"
                if _is_coloring(low):
                    state.service = text
                    state.step = "clarify_hair"
                    return f"{fa} Волосы сейчас окрашены или свой цвет? Были ли осветление, кератин?"
                state.step = "clarify"
                return f"{fa} {_clarify_question(state, text)}"
            follow = _follow_question(state)
            return f"{fa} {follow}" if follow else fa

    # 2. Старт
    if state.step == "start":
        intent = detect_intent(text)
        if not intent:
            return "Здравствуйте! Abramenko Studio. Что вас интересует — запись, модель, вакансия или обучение?"
        state.intent = intent
        if intent == "booking" and _is_coloring(low):
            state.service = text
            state.step = "clarify_hair"
            return "Балаяж — это красиво, но результат сильно зависит от того, что сейчас с волосами. Они сейчас окрашены или свой цвет?"
        state.step = "clarify"
        return _clarify_question(state, text)

    # 3. Уточнение по ветке
    if state.step == "clarify":
        _remember_clarify(state, text)
        if state.intent == "booking" and _is_coloring(low):
            if not state.hair:
                state.step = "clarify_hair"
                return "Понял. Волосы сейчас окрашены или свой цвет? Были ли осветление, кератин?"
        state.step = "time"
        return "Понял. Вам удобнее в будни или в выходные? Утром или ближе к вечеру?"

    if state.step == "clarify_hair":
        state.hair = text
        state.step = "time"
        return "Понял. Вам удобнее в будни или в выходные? Утром или ближе к вечеру?"

    # 4. Время
    if state.step == "time":
        state.time_pref = text
        state.step = "branch"
        return "Какой филиал удобнее — Букетова, 61 (Евразийский рынок) или Жамбыла, 127 Madame (Конституции Казахстана)?"

    # 5. Филиал
    if state.step == "branch":
        state.branch = text
        state.step = "await_name"
        return "Хорошо. Как вас зовут?"

    # 6. Имя
    if state.step == "await_name":
        if fa and "филиал" not in low:
            pass  # имя важнее
        state.name = text.split()[0].capitalize()
        state.step = "await_phone"
        return f"{state.name}, какой номер для связи — администратор перезвонит?"

    # 7. Телефон
    if state.step == "await_phone":
        if m:
            state.phone = m.group(0)
            state.step = "done"
            return f"Принял, {state.name}. {CLOSINGS.get(state.intent, CLOSINGS['booking'])}"
        return "Напишите номер в формате +7 ___ ___ __ __ — передам администратору."

    if state.step == "done":
        return "Хорошо, если что — пишите."

    return "Понял. Что вас интересует — запись, модель, вакансия или обучение?"


def _clarify_question(state: DialogState, text: str) -> str:
    if state.intent == "booking":
        return "Какая услуга интересует — окрашивание, стрижка, ногти, другое?"
    if state.intent == "model":
        state.step = "clarify"
        return "На какую процедуру хотите моделью? Какой сейчас цвет и состояние волос?"
    if state.intent == "vacancy":
        return "Какая специализация — парикмахер, ногти, брови? Есть опыт и портфолио?"
    if state.intent == "training":
        return "Какое направление обучения интересует? Есть опыт в профессии?"
    return "Что вас интересует?"


def _remember_clarify(state: DialogState, text: str):
    if state.intent == "booking" and not state.service:
        state.service = text


def _follow_question(state: DialogState) -> str:
    if not state.intent:
        return "Что вас интересует — запись, модель, вакансия или обучение?"
    if state.step in ("start", "clarify"):
        return "Какая услуга интересует?"
    if state.step == "time":
        return "Вам удобнее в будни или в выходные?"
    if state.step == "branch":
        return "Какой филиал удобнее — Букетова или Жамбыла?"
    if state.step == "await_name":
        return "Как вас зовут?"
    if state.step == "await_phone":
        return "Какой номер для связи?"
    return ""
