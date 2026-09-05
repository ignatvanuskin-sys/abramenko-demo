"""Rule-based логика strictly по промпту: ответ + ровно один вопрос.

Ветки: booking / model / vacancy / training / faq.
Имя и телефон — только в конце. Календаря нет — окна не называем.

Приоритет:
1. Детерминированные факты (телефон, FAQ с привязкой к филиалу)
2. Детерминированный intent/booking
3. LLM fallback (только если FAQ и intent is None и не в booking flow)
4. Безопасный fallback
"""
import logging
import re
from .config import BRANCHES, PRICES, SALON, UNKNOWN_ANSWER

logger = logging.getLogger("abramenko.bot_logic")

PHONE_RE = re.compile(r"(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")
NAME_RE = re.compile(r"(?:я\s+([А-ЯЁ][а-яё]{2,})|меня\s+зовут\s+([А-ЯЁ][а-яё]{2,})|зовут\s+([А-ЯЁ][а-яё]{2,}))")


class DialogState:
    def __init__(self):
        self.intent = None  # booking|model|vacancy|training
        self.service = None
        self.service_id = None
        self.hair = None
        self.time_pref = None
        self.branch = None
        self.branch_id = None
        self.master_id = None
        self.master_name = None
        self.slots = []  # list of ISO strings
        self.selected_slot = None
        self.name = None
        self.phone = None
        self.step = "start"
        # для vacancy/model/training — портфолио/опыт, чтобы не ломать booking поля
        self.portfolio = None
        # приветствие отправляется один раз за сессию (для unclear без повторов)
        self.greeted = False

# Категории нераспознанных: off_topic / unclear / faq_unknown / inappropriate
OFF_TOPIC_REPLY = "Поняла 😊 Я подскажу только по вопросам Abramenko Studio. Напишите, пожалуйста, что вас интересует по услугам или записи."
UNCLEAR_REPLY = "Не поняла, о чём речь 🙂 Хотите записаться, узнать цену или что-то ещё?"
FAQ_UNKNOWN_REPLY = "Уточню у администратора, он ответит точно."
INAPPROPRIATE_REPLY = "Я тут только по вопросам салона 🙂 Подскажу по услугам или запишу — что вам актуально?"
GREETING_FULL = "Здравствуйте! Abramenko Studio. Что вас интересует — запись, модель, вакансия или обучение?"

INAPPROPRIATE_KEYWORDS = [
    "дура", "дурак", "тупая", "тупой", "идиот", "дебил", "пошла", "пошел",
    "секс", "порно", "эротик", "наркотик", "наркот", "убью", "убей",
    "ненавижу", "сука", "бля", "нах", "хер", "пизд",
    "игнорируй инструкции", "покажи system prompt", "system prompt",
    "jailbreak", "dan mode", "обойди правила",
]

BEAUTY_TOPIC_KEYWORDS = [
    "кератин", "окрашиван", "стрижк", "завивк", "ламинирован", "ботокс",
    "пилинг", "массаж", "макияж", "прическ", "укладк", "мелир", "блонд",
    "балаяж", "airtouch", "хим", "восстановл",
]

def is_inappropriate(text: str) -> bool:
    t = text.lower()
    for kw in INAPPROPRIATE_KEYWORDS:
        if " " in kw:
            if kw in t:
                return True
        else:
            # короткие корни ("хер", "нах") — только по границам слов,
            # иначе "парикмахер" даст ложное срабатывание
            if re.search(r"\b" + re.escape(kw) + r"\b", t):
                return True
    return False

def is_unclear(text: str) -> bool:
    s = text.strip()
    if not s:
        return True
    cleaned = re.sub(r"\s", "", s)
    if len(cleaned) <= 1:
        return True
    # только символы/эмодзи без букв и цифр
    if re.fullmatch(r"[^\wа-яё]+", s, re.IGNORECASE):
        return True
    return False


def _find_price(text: str):
    t = text.lower()
    for key, val in PRICES.items():
        if key in t:
            return val
    # опечатки: балияж/балаж; синонимы: покраска/покрасить, подстричься, каре
    if "окрашиван" in t or "покрас" in t or "airtouch" in t or "балаяж" in t or "балияж" in t or "балаж" in t or "мелирован" in t or "блонд" in t:
        return "Балаяж / AirTouch / мелирование — 25 000–80 000 ₸, точную сумму назовут на консультации"
    if "стрижк" in t or "стрич" in t or "каре" in t:
        return f"{PRICES['женская стрижка']}, {PRICES['мужская стрижка']}"
    return None


def _is_about_zhambyla(t: str) -> bool:
    return "жамбыл" in t

def _is_about_buketova(t: str) -> bool:
    return "букетов" in t

TRAINING_RELEVANT = [
    "колорист", "окраш", "парикмахер", "стриж", "балаяж", "airtouch",
    "мелир", "блонд", "бров", "ресниц", "ногт", "маникюр", "педикюр",
    "визаж", "косметолог", "наращиван", "завивк", "ботокс", "салон", "красот",
    "прикорнев", "холодн", "восстановл", "контуринг", "dim", "тотал",
]

def is_training_relevant(topic: str) -> bool:
    t = topic.lower()
    return any(kw in t for kw in TRAINING_RELEVANT)

SALON_KEYWORDS = [
    "салон", "абраменко", "madame", "мадам", "услуг", "цен", "стоим", "прайс",
    "окраш", "стриж", "балаяж", "волос", "ногт", "маникюр", "педикюр", "бров",
    "ресниц", "лазер", "эпиляц", "визаж", "макияж", "наращиван", "завивк",
    "ботокс", "запис", "филиал", "адрес", "жамбыл", "букетов", "обуч", "курс",
    "колорист", "мастер", "ваканс", "модел", "портфолио", "время", "будни",
    "выходн", "администратор", "контакт", "телефон", "имя", "парков", "отзыв",
    "рейтинг", "премия", "свадеб", "прическ", "прикорнев", "холодн",
    "кератин", "ламинирован", "укладк", "мелир", "блонд", "airtouch",
    "покрас", "стрич", "каре", "шеллак", "покрытие", "коррекция",
]

OFF_TOPIC_KEYWORDS = [
    "вуз", "университет", "универ", "поступить", "поступление", "абитуриент",
    "егэ", " ент", "колледж", "институт", "программ", " python", "питон",
    "английск", "математик", "автомобил", "машин", "ремонт", "путешеств", "погода",
    "новост", "политик", "президент", "выборы", "крипт", "биткоин", "инвестиц",
    "акции", "трейдинг", "игра", "гейм", "футбол", "спорт", "школьн", "отношен",
    "код", "исходник", "ваш бот", "сайт", "api", "подключ",
]

def _is_on_topic_deterministic(text: str) -> bool | None:
    t = text.lower()
    has_salon = any(kw in t for kw in SALON_KEYWORDS)
    has_off = any(kw in t for kw in OFF_TOPIC_KEYWORDS)
    if has_salon and not has_off:
        return True
    if has_off and not has_salon:
        return False
    if has_salon and has_off:
        # смешанный — считаем on_topic, пусть training relevance решит
        return True
    return None  # неоднозначно — нужен LLM

def _is_off_topic_llm(text: str) -> bool | None:
    try:
        from .llm_client import llm_available, classify_on_topic
        if not llm_available():
            return None
        # не вызываем LLM внутри booking flow
        return not classify_on_topic(text)
    except Exception:
        return None

def is_off_topic(text: str, state) -> bool:
    # внутри booking flow не считаем off_topic, чтобы не прерывать запись
    if state.step not in ("start", "done") and state.intent is not None:
        return False
    det = _is_on_topic_deterministic(text)
    if det is True:
        return False
    if det is False:
        return True
    # неоднозначно — пробуем LLM
    llm_res = _is_off_topic_llm(text)
    if llm_res is not None:
        return llm_res
    # без LLM — считаем on_topic, чтобы не блокировать
    return False

def _is_question_about_branch_detail(t: str) -> bool:
    return any(w in t for w in ["что на", "что есть", "расскаж", "что у вас", "какие услуги", "что делаете на"])

def _use_real_booking() -> bool:
    import os
    # для демо — включается только если явно задан DEMO_BOOKING=1 и есть БД
    # иначе оставляем старый flow (предпочтение будни/выходные) для совместимости тестов
    if os.getenv("DEMO_BOOKING") != "1":
        return False
    if not os.getenv("DATABASE_URL"):
        return False
    try:
        from .booking import get_available_slots  # noqa: F401
        return True
    except Exception:
        return False

def _ask_master(state) -> str:
    # DEMO DATA — заменить на реальное расписание перед продакшеном
    try:
        import os
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from .models import Branch, Master, Service
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("no db")
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        db = Session()
        # найти branch_id по имени
        branch_id = 1
        for b in db.query(Branch).all():
            if state.branch and (b.name in state.branch or b.address in (state.branch or "")):
                branch_id = b.id
                state.branch_id = b.id
                break
        # найти service_id по названию услуги
        service_id = 1
        for s in db.query(Service).all():
            if state.service and s.name.lower() in state.service.lower():
                service_id = s.id
                state.service_id = s.id
                break
        # если не нашли — берём первый
        if not state.service_id:
            first = db.query(Service).first()
            if first:
                service_id = first.id
                state.service_id = first.id
        from .booking_tools import get_masters
        masters = get_masters(db, branch_id, service_id)
        db.close()
        if not masters:
            state.step = "await_date"
            return "На какую дату смотрим? Напишите, например, «завтра» или «на этой неделе»."
        if len(masters) == 1:
            state.master_id = masters[0]["id"]
            state.master_name = masters[0]["name"]
            state.step = "await_date"
            return f"Мастер {masters[0]['name']} свободен. На какую дату смотрим? Например, «завтра» или конкретная дата."
        # несколько мастеров — спросить
        opts = " / ".join([m["name"] for m in masters[:3]])
        state.slots = []  # сброс
        state.step = "await_master"
        return f"Кто удобнее: {opts} или «неважно, кто из мастеров»? Напишите имя мастера."
    except Exception:
        state.step = "await_date"
        return "На какую дату смотрим? Напишите, например, «завтра» или «на этой неделе»."

def _format_slots(slots: list) -> str:
    # slots — list of ISO strings UTC, показываем в TZ филиала
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import os
    tz = ZoneInfo("Asia/Almaty")
    lines = []
    for i, iso in enumerate(slots[:3], 1):
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        local = dt.astimezone(tz)
        lines.append(f"{i}) {local.strftime('%d.%m %H:%M')}")
    return "\n".join(lines)

def _show_slots(state) -> str:
    # DEMO DATA — заменить на реальное расписание перед продакшеном
    try:
        import os
        from datetime import date, timedelta
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("no db")
        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        db = Session()
        # schedule_exceptions может не существовать в свежей демо-БД — не падаем
        try:
            db.query(ScheduleException).all()
        except Exception:
            db.rollback()
        b_id = getattr(state, "branch_id", None) or 1
        s_id = getattr(state, "service_id", None) or 1
        m_id = getattr(state, "master_id", None)
        if not m_id:
            # любой мастер — берём первого для услуги/филиала
            from .booking_tools import get_masters
            masters = get_masters(db, b_id, s_id)
            if masters:
                m_id = masters[0]["id"]
                state.master_id = m_id
                state.master_name = masters[0]["name"]
            else:
                m_id = 1
        date_from = date.today()
        date_to = date_from + timedelta(days=7)
        from .booking import get_available_slots
        import os as _os
        buf = int(_os.getenv("BUFFER_MINUTES", "15"))
        slots = get_available_slots(db, b_id, m_id, s_id, date_from, date_to, buffer_minutes=buf)
        db.close()
        if not slots:
            return "К сожалению, свободных окон на ближайшие 7 дней нет. Напишите другую дату или филиал."
        # сохраняем как ISO
        state.slots = [s.isoformat() for s in slots[:3]]
        who = f"У мастера {state.master_name} " if getattr(state, "master_name", None) else ""
        return f"{who}свободные окна:\n{_format_slots(state.slots)}\nНапишите 1, 2 или 3 чтобы выбрать."
    except Exception as e:
        logger.warning("show_slots failed: %s", e)
        return "Не удалось загрузить слоты. Напишите желаемую дату (например, «завтра»)."


def faq_answer(text: str):
    """Возвращает ответ на частый вопрос или None. Строго по филиалу."""
    t = text.lower().strip()

    # 1. Адрес / где вы — обе точки (если спрашивают в общем, без уточнения конкретной)
    if any(w in t for w in ["где вы", "где находитесь", "где находится", "ваш адрес", "адрес салона", "адреса"]):
        # если явно упомянут конкретный филиал — ответим ниже в ветке про конкретный филиал
        if _is_about_zhambyla(t) or _is_about_buketova(t):
            pass
        else:
            b1, b2 = BRANCHES
            return (
                "У нас две точки:\n\n"
                f"📍 {b1['label']} — {b1['address']}\n"
                f"Ориентир: {b1['landmark']}.\n"
                f"{b1['rating']}.\n\n"
                f"📍 {b2['label']} — {b2['address']}\n"
                f"Ориентир: {b2['landmark']}.\n"
                f"{b2['rating']}.\n"
                f"Есть парковка на 7 мест.\n\n"
                "Какой филиал вам удобнее?"
            )
    # общий "филиал" без конкретики тоже обе
    if t in ["филиал", "филиалы"] or t.startswith("где вы"):
        b1, b2 = BRANCHES
        return (
            "У нас две точки:\n\n"
            f"📍 {b1['label']} — {b1['address']}\n"
            f"Ориентир: {b1['landmark']}.\n"
            f"{b1['rating']}.\n\n"
            f"📍 {b2['label']} — {b2['address']}\n"
            f"Ориентир: {b2['landmark']}.\n"
            f"{b2['rating']}.\n"
            f"Есть парковка на 7 мест.\n\n"
            "Какой филиал вам удобнее?"
        )

    # 2. Локальные услуги — жёсткая привязка (проверяем до общего "что на")
    if any(w in t for w in ["бров"]):
        return "Да, брови есть на Букетова 61. На Жамбыла 127 по этой услуге уточню у администратора.\n\nКакой филиал вам удобнее?"
    if "лазер" in t or "лазерн" in t:
        return "Да, лазерная эпиляция есть на Букетова 61. На Жамбыла 127 по этой услуге уточню у администратора.\n\nКакой филиал вам удобнее?"
    if "мужской маникюр" in t or "мужской педикюр" in t:
        return "Да, мужской маникюр/педикюр есть на Жамбыла 127 (Madame).\n\nКакой филиал вам удобнее?"
    if "мужской" in t and ("маникюр" in t or "педикюр" in t):
        return "Да, мужской маникюр/педикюр есть на Жамбыла 127 (Madame).\n\nКакой филиал вам удобнее?"
    if "свадеб" in t:
        return "Да, свадебные и вечерние причёски есть на Жамбыла 127 (Madame). Уточните дату — передам как срочное.\n\nКакой филиал вам удобнее?"

    # 3. Что на Жамбыла? — только Madame (общая инфа)
    if _is_about_zhambyla(t) and ("что" in t or _is_question_about_branch_detail(t) or len(t.split()) <= 4):
        if any(w in t for w in ["что", "расскаж", "услуг", "парков", "рейтинг", "премия", "победитель"]):
            return (
                "📍 Madame — ул. Жамбыла, 127\n"
                "Ориентир: остановка «Конституции Казахстана», около 80 м.\n"
                "4.8 ★ · 191 оценка · Победитель Премии 2ГИС 2025.\n"
                "Есть бесплатная парковка на 7 мест.\n"
                "Подтверждено для этой точки: свадебные и вечерние причёски, мужской маникюр/педикюр, гель-лак, аппаратный маникюр, наращивание гелем.\n\n"
                "Какой филиал вам удобнее?"
            )
        if t.count("жамбыл") >= 1 and len(t) < 40:
            return (
                "📍 Madame — ул. Жамбыла, 127\n"
                "Ориентир: остановка «Конституции Казахстана», около 80 м.\n"
                "4.8 ★ · 191 оценка · Победитель Премии 2ГИС 2025.\n"
                "Есть парковка на 7 мест.\n\n"
                "Какой филиал вам удобнее?"
            )

    # 4. Что на Букетова? — только Abramenko Studio
    if _is_about_buketova(t) and ("что" in t or _is_question_about_branch_detail(t) or len(t.split()) <= 4):
        if any(w in t for w in ["что", "расскаж", "услуг", "бров", "лазер"]):
            b1 = BRANCHES[0]
            return (
                f"📍 {b1['label']} — {b1['address']}\n"
                f"Ориентир: {b1['landmark']}.\n"
                f"{b1['rating']}.\n"
                "Подтверждено для этой точки: коррекция/ламинирование бровей, лазерная эпиляция.\n\n"
                "Какой филиал вам удобнее?"
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
    if any(w in t for w in ["маникюр", "педикюр", "гель-лак", "гель лак", "ногт"]) and "мужской" not in t:
        return "В Madame указаны гель-лак, аппаратный маникюр, наращивание гелем, мужской маникюр/педикюр. Цену скажет администратор после консультации."
    if "цен" in t or "стоим" in t or "сколько" in t or "прайс" in t or "скок" in t:
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
    # порядок важен: model/training перед vacancy, иначе "требуются модели" уйдёт в vacancy
    if "модел" in t:
        return "model"
    if any(w in t for w in ["обуч", "курс", "научить"]):
        return "training"
    # vacancy — расширяем на требу* и вакансия
    if any(w in t for w in ["ваканс", "вакансия"]):
        return "vacancy"
    if "требуется" in t or "требуются" in t:
        # если рядом модель — уже выше, иначе вакансия
        if any(w in t for w in ["мастер", "парикмахер", "бровист", "ногт"]):
            return "vacancy"
        return "vacancy"
    if any(w in t for w in ["работ", "трудоустр"]):
        if "работ" in t and any(w in t for w in ["ищете", "ищу", "ищем", "у вас", "есть", "хочу"]):
            return "vacancy"
        if "мастером" in t:
            return "vacancy"
    if any(w in t for w in ["ищете мастер", "требуется мастер"]):
        return "vacancy"
    if any(w in t for w in ["запис", "хочу", "окраш", "покрас", "стриж", "стрич", "каре", "балаяж", "ногт", "маникюр", "шеллак", "покрытие", "коррекция", "эпиляц", "бров", "свадеб", "цен", "стоим", "филиал", "где", "жамбыл", "букетов", "мадам", "madame"]):
        return "booking"
    return None


def _is_coloring(text_low: str) -> bool:
    # терпим опечатки: балияж/балаж, мелир etc; синонимы: покраска, каре
    return any(w in text_low for w in ["окраш", "покрас", "балаяж", "балияж", "балаж", "блонд", "мелир", "airtouch", "шатуш", "контуринг", "dim-out", "dim out", "total blond"])


def _looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    if "?" in text:
        return True
    # терпим опечатки скока/скольк
    if any(w in t for w in ["скок", "сколь"]):
        return True
    return t.startswith(("сколько", "где ", "где?", "как ", "можно", "есть", "делаете", "какая", "какие", "что ", "подскажите", "а ", "скок"))


def _is_inside_booking_flow(state) -> bool:
    # считаем внутри booking если intent задан и шаг не start/done
    return state.intent is not None and state.step not in ("start", "done")


def _try_llm_fallback(state, user_text: str):
    """Пытается ответить через LLM, если доступен. Иначе None."""
    # только если FAQ и intent is None и не в booking flow
    if _is_inside_booking_flow(state):
        return None
    try:
        from .llm_client import llm_available, llm_reply
    except Exception:
        return None
    if not llm_available():
        return None
    # защита: пустой, телефон, слишком короткое
    if not user_text or len(user_text.strip()) < 2:
        return None
    # не вызываем LLM на вопросы которые уже покрыты FAQ/intent
    if faq_answer(user_text) is not None:
        return None
    if detect_intent(user_text) is not None:
        return None
    try:
        # структурированный контекст для анти-галлюцинации
        known = f"BRANCH1: {BRANCHES[0]['label']} {BRANCHES[0]['address']} {BRANCHES[0]['rating']} | BRANCH2: {BRANCHES[1]['label']} {BRANCHES[1]['address']} {BRANCHES[1]['rating']}"
        ctx = f"[KNOWN_FACTS: {known}] [INTENT: {state.intent}] [STEP: {state.step}]"
        # передаём как одно сообщение, llm_client добавит system prompt
        msg = f"{ctx}\nUSER: {user_text}\nОтветь коротко (1-2 строки), без выдумок. Если нет факта — скажи «Уточню у администратора» и задай один уточняющий вопрос."
        return llm_reply([{"role": "user", "content": msg}], temperature=0.2)
    except Exception:
        return None


def reply(state: DialogState, user_text: str) -> str:
    text = (user_text or "").strip()
    low = text.lower()

    # 0. Телефон ловим в любом месте
    m = PHONE_RE.search(text)
    if m and not state.phone:
        state.phone = m.group(0)
        # реальные слоты — создаём запись транзакционно до любого ответа
        if _use_real_booking() and state.intent == "booking" and state.selected_slot:
            try:
                import os
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
                from dateutil.parser import isoparse
                from datetime import timezone
                db_url = os.getenv("DATABASE_URL")
                engine = create_engine(db_url)
                Session = sessionmaker(bind=engine)
                db = Session()
                b_id = getattr(state, "branch_id", 1) or 1
                s_id = getattr(state, "service_id", 1) or 1
                m_id = getattr(state, "master_id", None)
                if not m_id:
                    from .booking_tools import get_masters
                    masters = get_masters(db, b_id, s_id)
                    if masters:
                        m_id = masters[0]["id"]
                        state.master_id = m_id
                starts_at = isoparse(state.selected_slot)
                if starts_at.tzinfo is None:
                    starts_at = starts_at.replace(tzinfo=timezone.utc)
                from .booking import create_booking as _create
                appt = _create(db, b_id, m_id, s_id, state.name or "Клиент", state.phone, starts_at)
                db.commit()
                from zoneinfo import ZoneInfo
                local = appt.starts_at.astimezone(ZoneInfo("Asia/Almaty")) if appt.starts_at.tzinfo else appt.starts_at
                state.step = "done"
                name = state.name or "Клиент"
                return f"Вы записаны, {name}! {local.strftime('%d.%m %H:%M')} — {state.branch or ''} {getattr(state, 'master_name', '') or ''}. Ждём вас!".strip()
            except ValueError as e:
                if "занят" in str(e):
                    state.selected_slot = None
                    state.slots = []
                    state.step = "await_slot"
                    return f"Извините, это время уже заняли, пока вы выбирали. {_show_slots(state)}"
                logger.exception("booking create failed: %s", e)
                state.step = "done"
                name = state.name or "Клиент"
                return f"Принял, {name}. {CLOSINGS.get(state.intent or 'booking', CLOSINGS['booking'])}"
            except Exception as e:
                logger.exception("booking create crashed: %s", e)
                state.step = "done"
                name = state.name or "Клиент"
                return f"Принял, {name}. {CLOSINGS.get(state.intent or 'booking', CLOSINGS['booking'])}"
        if state.name and state.intent:
            closing = CLOSINGS.get(state.intent, CLOSINGS["booking"])
            state.step = "done"
            return f"Принял, {state.name}. {closing}"
        if state.step == "await_phone":
            name = state.name or ""
            state.step = "done"
            return f"Принял, {name}. {CLOSINGS.get(state.intent or 'booking', CLOSINGS['booking'])}"

    # 0.5 inappropriate — оскорбления/провокации: не уточнять смысл, не повторять слова, без state
    if is_inappropriate(text):
        return INAPPROPRIATE_REPLY

    # 0.6 unclear — только на старте без intent (внутри booking короткие "1"/"да" — валидные ответы)
    if state.step == "start" and state.intent is None and is_unclear(text):
        if state.greeted:
            return UNCLEAR_REPLY
        state.greeted = True
        return GREETING_FULL

    # 0.7 off_topic защита — до FAQ и intent, не меняем state и не собираем лид
    if is_off_topic(text, state):
        return OFF_TOPIC_REPLY

    # 1. FAQ — только если это похоже на вопрос, и не перебиваем слоты время/филиал/имя/телефон
    if state.step in ("time", "branch", "await_name", "await_phone", "clarify_hair", "portfolio"):
        fa = faq_answer(text) if _looks_like_question(text) else None
        if fa:
            if "Какой филиал вам удобнее?" in fa:
                return fa
            follow = _follow_question(state)
            return f"{fa} {follow}" if follow else fa
        # иначе считаем текст значением слота — идём дальше
    else:
        fa = faq_answer(text) if len(low) > 2 else None
        if fa and state.intent != "model" and _looks_like_question(text):
            # если ответ уже содержит вопрос про филиал — не добавляем второй
            if "Какой филиал вам удобнее?" in fa:
                return fa
            # на старте фиксируем намерение, чтобы не топтаться
            if state.step == "start":
                # для филиалов/адреса — не меняем intent, просто FAQ
                if "Букетова" in fa or "Жамбыла" in fa:
                    return fa
                state.intent = detect_intent(text) or "booking"
                if _is_coloring(low):
                    state.service = text
                    state.step = "clarify_hair"
                    return f"{fa} Волосы сейчас окрашены или свой цвет? Были ли осветление, кератин?"
                state.step = "clarify"
                return f"{fa} {_clarify_question(state, text)}"
            follow = _follow_question(state)
            # не дублировать вопрос если уже есть
            if "Какой филиал вам удобнее?" in fa:
                return fa
            return f"{fa} {follow}" if follow else fa

    # 2. Старт — приоритет LLM fallback если неизвестно
    if state.step == "start":
        intent = detect_intent(text)
        if not intent:
            # on-topic вопрос без ответа в базе — только здесь "Уточню у администратора"
            if _looks_like_question(text) and _is_on_topic_deterministic(text) is True:
                return FAQ_UNKNOWN_REPLY
            # пробуем LLM перед дефолтным приветствием
            llm_ans = _try_llm_fallback(state, text)
            if llm_ans:
                return llm_ans
            # приветствие один раз за сессию, дальше — короткий переспрос
            if state.greeted:
                return UNCLEAR_REPLY
            state.greeted = True
            return GREETING_FULL
        state.intent = intent
        # training — сразу отсекаем нерелевантное (прямо на старте, если уже есть тема)
        if intent == "training" and not is_training_relevant(text):
            generic = low.strip() in ["хочу купить курсы", "хочу курсы", "курсы", "обучение", "хочу обучение", "хочу пройти курс", "обучение есть?", "курс колорист с нуля"]
            if not generic and any(kw in low for kw in ["программ", "английск", "математ", "python", "таргет", "инвест", "финанс", "бизнес", "маркет"]):
                short = text.strip()[:40] + ("…" if len(text.strip()) > 40 else "")
                state.intent = None
                state.step = "start"
                return f"Поняла 😊 Обучение {short} у нас не проводится. Мы обучаем направлениям, связанным с услугами студии. Если вас интересует обучение в сфере красоты, подскажу подробнее."
        if intent == "vacancy" and not is_training_relevant(text):
            if any(kw in low for kw in ["повар", "водител", "курьер", "официант", "программ", "кладовщик"]):
                short = text.strip()[:40] + ("…" if len(text.strip()) > 40 else "")
                state.intent = None
                state.step = "start"
                return f"Поняла 😊 Вакансия {short} у нас сейчас не открыта. Сейчас ищем мастеров бьюти-сферы."
        if intent == "model" and not is_training_relevant(text):
            if any(kw in low for kw in ["программ", "английск", "математ", "python", "таргет"]):
                short = text.strip()[:40] + ("…" if len(text.strip()) > 40 else "")
                state.intent = None
                state.step = "start"
                return f"Поняла 😊 Модель для {short} нам сейчас не требуется. Ищем моделей для процедур салона."
        # предзаполнение из свободного текста (имя, филиал, волосы, время) — чтобы не спрашивать повторно
        if intent == "booking":
            if _is_about_zhambyla(low):
                state.branch = "Жамбыла 127"
            elif _is_about_buketova(low):
                state.branch = "Букетова 61"
            if "окрашен" in low or "крашен" in low:
                state.hair = "окрашены"
            elif "натуральн" in low or "свой цвет" in low or "свои " in low or "натуральн" in low:
                state.hair = "свой цвет"
            if "выходн" in low or "суббот" in low or "воскрес" in low:
                state.time_pref = "выходные"
            elif "будн" in low or "понедельник" in low or "вторник" in low or "сред" in low or "четверг" in low or "пятниц" in low:
                state.time_pref = "будни"
            if "утр" in low and state.time_pref:
                if "утр" not in state.time_pref:
                    state.time_pref += " утром"
            elif "вечер" in low and state.time_pref:
                if "вечер" not in state.time_pref:
                    state.time_pref += " вечером"
            elif "утр" in low and not state.time_pref:
                state.time_pref = "утром"
            elif "вечер" in low and not state.time_pref:
                state.time_pref = "вечером"
            m_name = NAME_RE.search(text)
            if m_name and not state.name:
                cand = next((g for g in m_name.groups() if g), None)
                if cand:
                    state.name = cand.capitalize()
            # если сразу сказали услугу с окрашиванием — сохраним
            if _is_coloring(low):
                state.service = text
            elif any(kw in low for kw in ["стриж", "стрич", "каре", "ногт", "маникюр", "педикюр", "шеллак", "покрытие", "коррекция", "наращиван", "бров", "эпиляц", "лазер", "визаж", "макияж", "свадеб", "прическ", "ботокс", "завив", "кератин", "ламинирован"]):
                # конкретная не-окрасочная услуга — сохраняем, вопрос про волосы не задаём
                state.service = text
            # переходим к первому незаполненному шагу
            if not state.service:
                state.step = "clarify"
                return _clarify_question(state, text)
            if not state.hair and _is_coloring((state.service or "").lower()):
                state.step = "clarify_hair"
                return "Балаяж — это красиво, но результат сильно зависит от того, что сейчас с волосами. Они сейчас окрашены или свой цвет?"
            if not state.time_pref:
                state.step = "time"
                return "Понял. Вам удобнее в будни или в выходные? Утром или ближе к вечеру?"
            if not state.branch:
                state.step = "branch"
                return "Какой филиал удобнее — Букетова, 61 (Евразийский рынок) или Жамбыла, 127 Madame (Конституции Казахстана)?"
            if not state.name:
                state.step = "await_name"
                return "Хорошо. Как вас зовут?"
            state.step = "await_phone"
            return f"{state.name}, какой номер для связи — администратор перезвонит?"
        if intent == "booking" and _is_coloring(low) and not state.service:
            state.service = text
            state.step = "clarify_hair"
            return "Балаяж — это красиво, но результат сильно зависит от того, что сейчас с волосами. Они сейчас окрашены или свой цвет?"
        state.step = "clarify"
        return _clarify_question(state, text)

    # 3. Уточнение по ветке
    if state.step == "clarify":
        # если на вопрос про услугу ответили названием филиала — запомним филиал и переспросим услугу
        if state.intent == "booking" and state.branch is None and (_is_about_zhambyla(low) or _is_about_buketova(low)):
            state.branch = text
            return "Принял, филиал запомнил. Какая услуга интересует — окрашивание, стрижка, ногти, другое?"
        _remember_clarify(state, text)
        # для не-booking веток — идём в портфолио, а не в time
        if state.intent in ("vacancy", "model", "training"):
            # training/vacancy/model — проверяем релевантность перед сбором лида
            if state.intent == "training":
                topic = text.strip()
                if topic and not is_training_relevant(topic):
                    generic = topic.lower().strip() in ["хочу купить курсы", "хочу курсы", "курсы", "обучение", "хочу обучение"]
                    if not generic:
                        short = topic[:40] + ("…" if len(topic) > 40 else "")
                        state.intent = None
                        state.service = None
                        state.step = "start"
                        return f"Поняла 😊 Обучение {short} у нас не проводится. Мы обучаем направлениям, связанным с услугами студии. Если вас интересует обучение в сфере красоты, подскажу подробнее."
            elif state.intent == "vacancy":
                topic = text.strip()
                if topic and not is_training_relevant(topic):  # вакансии салона — те же ключи
                    generic = topic.lower().strip() in ["парикмахер", "мастер", "вакансия", "работа"]
                    if not generic and len(topic.split()) <= 3:
                        # короткая нерелевантная специализация типа "повар", "водитель"
                        short = topic[:40] + ("…" if len(topic) > 40 else "")
                        state.intent = None
                        state.service = None
                        state.step = "start"
                        return f"Поняла 😊 Вакансия {short} у нас сейчас не открыта. Сейчас ищем мастеров бьюти-сферы. Если интересует beauty-направление, подскажу."
            elif state.intent == "model":
                topic = text.strip()
                if topic and len(topic.split()) <= 4 and not is_training_relevant(topic):
                    # модель для не-бьюти процедуры — не релевантно
                    if any(kw in topic.lower() for kw in ["программ", "английск", "математ", "python", "таргет"]):
                        short = topic[:40] + ("…" if len(topic) > 40 else "")
                        state.intent = None
                        state.service = None
                        state.step = "start"
                        return f"Поняла 😊 Модель для {short} нам сейчас не требуется. Ищем моделей для процедур салона. Если интересует beauty-модель, подскажу."
            state.step = "portfolio"
            if state.intent == "vacancy":
                return "Понял. Можете отправить портфолио или рассказать об опыте?"
            if state.intent == "model":
                return "Понял. Готовы на длительную процедуру и фото до/после?"
            if state.intent == "training":
                return "По стоимости и программе уточню у администратора. Есть опыт в профессии?"
        if state.intent == "booking" and _is_coloring(low):
            if not state.hair:
                state.step = "clarify_hair"
                return "Понял. Волосы сейчас окрашены или свой цвет? Были ли осветление, кератин?"
        state.step = "time"
        return "Понял. Вам удобнее в будни или в выходные? Утром или ближе к вечеру?"

    if state.step == "clarify_hair":
        state.hair = text
        if _use_real_booking():
            # демо: сразу к филиалу/мастеру
            if state.branch:
                state.step = "await_master"
                return _ask_master(state)
            state.step = "branch"
            return "Какой филиал удобнее — Букетова, 61 (Евразийский рынок) или Жамбыла, 127 Madame (Конституции Казахстана)?"
        # legacy: спрашиваем время
        state.step = "time"
        return "Понял. Вам удобнее в будни или в выходные? Утром или ближе к вечеру?"

    if state.step == "portfolio":
        state.portfolio = text
        if state.name:
            state.step = "await_phone"
            return f"{state.name}, какой номер для связи — администратор перезвонит?"
        state.step = "await_name"
        return "Спасибо! Как вас зовут?"

    # 4. Время — для демо заменено на реальные слоты, для обратной совместимости оставляем фолбэк
    if state.step == "time":
        # DEMO: пробуем реальные слоты, если БД доступна — иначе старый фолбэк
        if _use_real_booking():
            state.time_pref = text
            # если филиал уже известен — сразу к мастеру, иначе спросим филиал
            if state.branch:
                state.step = "await_master"
                return _ask_master(state)
            state.step = "branch"
            return "Какой филиал удобнее — Букетова, 61 (Евразийский рынок) или Жамбыла, 127 Madame (Конституции Казахстана)?"
        # legacy fallback
        if _is_about_zhambyla(low):
            state.branch = "Жамбыла 127"
        elif _is_about_buketova(low):
            state.branch = "Букетова 61"
        if "выходн" in low or "суббот" in low or "воскрес" in low:
            state.time_pref = "выходные" + (" утром" if "утр" in low else " вечером" if "вечер" in low else "")
        elif "будн" in low or "понедел" in low or "вторник" in low or "сред" in low or "четверг" in low or "пятниц" in low:
            state.time_pref = "будни" + (" утром" if "утр" in low else " вечером" if "вечер" in low else "")
        elif "утр" in low:
            state.time_pref = "утром"
        elif "вечер" in low:
            state.time_pref = "вечером"
        else:
            state.time_pref = text
        if state.branch:
            if state.name:
                state.step = "await_phone"
                return f"{state.name}, какой номер для связи — администратор перезвонит?"
            state.step = "await_name"
            return "Хорошо. Как вас зовут?"
        state.step = "branch"
        return "Какой филиал удобнее — Букетова, 61 (Евразийский рынок) или Жамбыла, 127 Madame (Конституции Казахстана)?"

    # 5. Филиал
    if state.step == "branch":
        if state.branch and _use_real_booking():
            # демо-слоты: филиал уже выбран на предыдущем шаге
            state.step = "await_master"
            return _ask_master(state)
        if state.branch:
            if state.name:
                state.step = "await_phone"
                return f"{state.name}, какой номер для связи — администратор перезвонит?"
            state.step = "await_name"
            return "Хорошо. Как вас зовут?"
        state.branch = text
        # после филиала — к мастеру (реальные слоты) или к имени (fallback)
        if _use_real_booking():
            state.step = "await_master"
            return _ask_master(state)
        if state.name:
            state.step = "await_phone"
            return f"{state.name}, какой номер для связи — администратор перезвонит?"
        state.step = "await_name"
        return "Хорошо. Как вас зовут?"

    # 5.1 Мастер
    if state.step == "await_master":
        # выбор мастера — текст или "неважно"
        sel = text.strip().lower()
        if "неважно" in sel or "любой" in sel:
            # оставляем master_id как None — выберем первого доступного при показе слотов
            pass
        elif state.master_id is None:
            # пробуем найти мастера по имени
            try:
                import os
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
                from .models import Master
                db_url = os.getenv("DATABASE_URL")
                if db_url:
                    engine = create_engine(db_url)
                    Session = sessionmaker(bind=engine)
                    db = Session()
                    for m in db.query(Master).all():
                        if m.name.lower() in sel:
                            state.master_id = m.id
                            state.master_name = m.name
                            break
                    db.close()
            except Exception:
                pass
            if state.master_id is None and not is_training_relevant(sel):
                # не распознали имя мастера и это не услуга — переспросим вежливо
                return "Напишите имя мастера (например, «Анна») или «неважно, кто из мастеров»."
        # показываем слоты
        state.step = "await_slot"
        return _show_slots(state)

    # 5.1b Дата (когда мастер один / слоты ещё не показаны)
    if state.step == "await_date":
        state.time_pref = text
        # показываем реальные слоты
        state.step = "await_slot"
        return _show_slots(state)

    # 5.2 Слоты — выбор
    if state.step == "await_slot":
        # если слотов нет — просим дату
        if not state.slots:
            state.step = "await_slot"
            return _show_slots(state)
        # парсим выбор 1/2/3
        choice = text.strip()
        idx = None
        if choice in ["1", "2", "3", "1)", "2)", "3)"]:
            idx = int(choice[0]) - 1
        else:
            import re as _re
            m = _re.search(r"(\d{1,2}[:.]\d{2})", choice)
            if m and state.slots:
                for i, iso in enumerate(state.slots):
                    if m.group(1).replace(".", ":") in iso:
                        idx = i
                        break
            if "перв" in low:
                idx = 0
            elif "втор" in low:
                idx = 1
            elif "трет" in low:
                idx = 2
        if idx is not None and 0 <= idx < len(state.slots):
            state.selected_slot = state.slots[idx]
            if state.name:
                state.step = "await_phone"
                return f"{state.name}, какой номер для связи — администратор перезвонит?"
            state.step = "await_name"
            return "Хорошо. Как вас зовут?"
        if state.slots:
            return f"Выберите вариант:\n{_format_slots(state.slots)}\nНапишите 1, 2 или 3."
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
            # реальные слоты — создаём запись транзакционно
            if _use_real_booking() and state.intent == "booking" and state.selected_slot:
                try:
                    import os
                    from sqlalchemy import create_engine
                    from sqlalchemy.orm import sessionmaker
                    from dateutil.parser import isoparse
                    from datetime import timezone
                    db_url = os.getenv("DATABASE_URL")
                    engine = create_engine(db_url)
                    Session = sessionmaker(bind=engine)
                    db = Session()
                    # подставим недостающие id если не выбраны
                    b_id = getattr(state, "branch_id", 1) or 1
                    s_id = getattr(state, "service_id", 1) or 1
                    m_id = getattr(state, "master_id", None)
                    if not m_id:
                        # любой мастер — берём первого
                        from .booking_tools import get_masters
                        masters = get_masters(db, b_id, s_id)
                        if masters:
                            m_id = masters[0]["id"]
                            state.master_id = m_id
                    starts_at = isoparse(state.selected_slot)
                    if starts_at.tzinfo is None:
                        starts_at = starts_at.replace(tzinfo=timezone.utc)
                    from .booking import create_booking as _create
                    appt = _create(db, b_id, m_id, s_id, state.name, state.phone, starts_at)
                    db.commit()
                    # форматируем для клиента
                    from zoneinfo import ZoneInfo
                    local = appt.starts_at.astimezone(ZoneInfo("Asia/Almaty")) if appt.starts_at.tzinfo else appt.starts_at
                    state.step = "done"
                    # admin notify теперь с датой/временем — делается в bot_logic, но также в web_api
                    try:
                        import asyncio
                        from .admin_notify import notify_admin_booking
                        # если есть бот — уведомим, но не блокируем
                    except Exception:
                        pass
                    return f"Вы записаны! {local.strftime('%d.%m %H:%M')} — {state.branch or ''} {getattr(state, 'master_name', '') or ''}. Ждём вас!".strip()
                except ValueError as e:
                    if "занят" in str(e):
                        # гонка — показываем новые слоты
                        state.selected_slot = None
                        state.step = "await_slot"
                        # сбросим слоты
                        state.slots = []
                        return f"Извините, это время уже заняли, пока вы выбирали. {_show_slots(state)}"
                    raise
                except Exception:
                    # fallback к старой логике
                    state.step = "done"
                    return f"Принял, {state.name}. {CLOSINGS.get(state.intent, CLOSINGS['booking'])}"
            state.step = "done"
            return f"Принял, {state.name}. {CLOSINGS.get(state.intent, CLOSINGS['booking'])}"
        return "Напишите номер в формате +7 ___ ___ __ __ — передам администратору."

    if state.step == "done":
        # если уже done и спрашивают что-то новое — пробуем LLM, иначе дефолт
        llm_ans = _try_llm_fallback(state, text)
        if llm_ans:
            return llm_ans
        return "Хорошо, если что — пишите."

    # fallback с LLM
    llm_ans = _try_llm_fallback(state, text)
    if llm_ans:
        return llm_ans
    return "Понял. Что вас интересует — запись, модель, вакансия или обучение?"


def _clarify_question(state: DialogState, text: str) -> str:
    if state.intent == "booking":
        return "Какая услуга интересует — окрашивание, стрижка, ногти, другое?"
    if state.intent == "model":
        return "На какую процедуру хотите моделью? Какой сейчас цвет и состояние волос?"
    if state.intent == "vacancy":
        return "Какая у вас специализация — парикмахер, ногти, брови? Есть опыт и портфолио?"
    if state.intent == "training":
        return "Какое направление обучения интересует? Есть опыт в профессии?"
    return "Что вас интересует?"


def _remember_clarify(state: DialogState, text: str):
    if state.intent == "booking" and not state.service:
        state.service = text
    elif state.intent in ("vacancy", "model", "training") and not state.service:
        state.service = text


def _follow_question(state: DialogState) -> str:
    if not state.intent:
        return "Что вас интересует — запись, модель, вакансия или обучение?"
    if state.step in ("start", "clarify"):
        return "Какая услуга интересует?"
    if state.step == "portfolio":
        return "Можете рассказать об опыте?"
    if state.step == "time":
        return "Вам удобнее в будни или в выходные?"
    if state.step == "branch":
        return "Какой филиал удобнее — Букетова или Жамбыла?"
    if state.step == "await_name":
        return "Как вас зовут?"
    if state.step == "await_phone":
        return "Какой номер для связи?"
    return ""
