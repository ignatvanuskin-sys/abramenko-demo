"""Премиум-эмодзи Telegram — только для Telegram-транспорта.

bot_logic/web/WhatsApp НЕ трогаем: tg-теги там отобразятся сырым текстом.
Всё маппим только из таблицы владельца, ID не выдумываем.
Обычные эмодзи, которых нет в таблице, вычищаются (правило владельца).
"""
from __future__ import annotations

import re as _re

# emoji -> premium emoji-id (таблица владельца)
EMOJI_IDS: dict[str, str] = {
    "🙂": "5870764288364252592",  # Смайл улыбка
    "😊": "5870764288364252592",  # ближайший из таблицы
    "🔔": "6039486778597970865",  # Уведомление
    "📍": "6042011682497106307",  # Геометка
    "👤": "5870994129244131212",  # Профиль
    "✅": "5870633910337015697",  # Галочка
    "❌": "5870657884844462243",  # Крестик
    "📅": "5890937706803894250",  # Календарь
    "⏰": "5983150113483134607",  # Часы
    "ℹ": "6028435952299413210",  # Инфо
    "🎉": "6041731551845159060",  # Ура
    "📊": "5870930636742595124",  # Рост график
    "🖋": "5870676941614354370",  # Карандаш
    "✍": "5870753782874246579",  # Писать
    "🖌": "6050679691004612757",  # Кисточка
}


def _load_extra_ids() -> dict[str, str]:
    """Доп. маппинг из env TG_PREMIUM_EMOJI_EXTRA ("эмодзи:id,...").

    Позволяет добавить premium-ID для новых эмодзи без изменения кода:
    владелец присылает ID из Bot API, оператор кладёт в Railway Variables.
    Битые пары игнорируются, код не падает.
    """
    import os as _os
    extra: dict[str, str] = {}
    raw = (_os.getenv("TG_PREMIUM_EMOJI_EXTRA") or "").strip()
    if not raw:
        return extra
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        emoji, eid = pair.split(":", 1)
        emoji, eid = emoji.strip(), eid.strip()
        if emoji and eid.isdigit():
            extra[emoji] = eid
    return extra


def emoji_ids() -> dict[str, str]:
    """Полная таблица: владелец + env-дополнения (env побеждает при конфликте)."""
    return {**EMOJI_IDS, **_load_extra_ids()}

# Иконки для кнопок (icon_custom_emoji_id, обычных эмодзи в тексте кнопок нет)
ICON_BRANCH = "6042011682497106307"    # 📍 Геометка
ICON_TIME = "5890937706803894250"      # 📅 Календарь
ICON_CONTACT = "5870994129244131212"   # 👤 Профиль
ICON_BRUSH = "6050679691004612757"     # 🖌 Кисточка


# Всё остальное из эмодзи-блоков вычищается. ★/☆ оставляем — это текстовые
# символы рейтинга, а не эмодзи, и в таблице их нет.
_STRIP_RE = _re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u2604\u2606-\u26FF\u2700-\u27BF"
    "\u2B00-\u2BFF\uFE0F\u200d\U0001F1E6-\U0001F1FF]"
)


def premium(text: str) -> str:
    """Известные эмодзи → <tg-emoji>, остальные обычные эмодзи — удалить."""
    if not text:
        return text
    ids = emoji_ids()
    # сначала чистим несопоставленные, потом ставим теги (иначе strip съест эмодзи внутри тегов)
    mapped = set(ids)
    text = "".join(ch for ch in text if ch in mapped or not _STRIP_RE.match(ch))
    for emoji, eid in ids.items():
        if emoji in text:
            text = text.replace(emoji, f'<tg-emoji emoji-id="{eid}">{emoji}</tg-emoji>')
    text = _re.sub(r"\n +", "\n", text)
    text = _re.sub(r" {2,}", " ", text)
    return text.strip()
