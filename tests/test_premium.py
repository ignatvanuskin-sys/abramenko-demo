import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tg_premium import EMOJI_IDS, premium
from app.bot_logic import DialogState, reply


def test_premium_replaces_mapped():
    import re
    out = premium("Поняла 🙂 Запись ✅")
    assert '<tg-emoji emoji-id="5870764288364252592">🙂</tg-emoji>' in out
    assert '<tg-emoji emoji-id="5870633910337015697">✅</tg-emoji>' in out
    # вне тегов обычных эмодзи из таблицы не осталось
    bare = re.sub(r'<tg-emoji[^>]*>.*?</tg-emoji>', '', out)
    assert "🙂" not in bare and "✅" not in bare


def test_premium_strips_unmapped():
    # обычных эмодзи вне таблицы быть не должно — только premium ID владельца
    out = premium("Балаяж 💇 стоит 25 000 ₸ 📞")
    assert "💇" not in out and "📞" not in out
    assert "<tg-emoji" not in out


def test_premium_no_regular_emoji_left():
    import re
    from app.bot_logic import DialogState, reply
    strip_re = re.compile(
        "[\U0001F000-\U0001FAFF\u2600-\u2604\u2606-\u26FF\u2700-\u27BF"
        "\u2B00-\u2BFF\uFE0F\u200d\U0001F1E6-\U0001F1FF]"
    )
    samples = ["хочу балаяж", "окрашены", "будни", "Жамбыла", "Айгерим",
               "+7 707 123 45 67", "где вы?", "сколько стоит балаяж?",
               "как поступить в вуз", "ты дура", "Здравствуйте"]
    for msg in samples:
        out = premium(reply(DialogState(), msg))
        bare = re.sub(r'<tg-emoji[^>]*>.*?</tg-emoji>', '', out)
        assert not strip_re.search(bare), msg
    # звёздочка рейтинга сохраняется
    assert "★" in premium("4.8 ★ · 191 оценка")


def test_premium_empty():
    assert premium("") == ""
    assert premium("просто текст") == "просто текст"


def test_bot_logic_has_no_tg_tags():
    # bot_logic общий для web/WhatsApp — tg-тегов там быть не должно
    s = DialogState()
    for msg in ["хочу балаяж", "окрашены", "будни", "Жамбыла", "Айгерим", "+7 707 123 45 67",
                "где вы?", "сколько стоит балаяж?", "как поступить в вуз", "ты дура"]:
        r = reply(DialogState(), msg)
        assert "<tg-emoji" not in r, msg


def test_keyboards_icons_valid():
    from app.keyboards import kb_services, kb_time, kb_branch, kb_contact_request
    import re
    valid = set(EMOJI_IDS.values())
    for kb in (kb_services(), kb_time(), kb_branch(), kb_contact_request()):
        for row in kb.keyboard:
            for btn in row:
                if btn.icon_custom_emoji_id is not None:
                    assert btn.icon_custom_emoji_id in valid, btn.text
                # в тексте кнопок обычных эмодзи нет
                assert not re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", btn.text), btn.text


def test_notify_premium_flag():
    import asyncio
    from unittest.mock import AsyncMock
    from app.admin_notify import notify_admin, build_admin_message
    import os
    os.environ["TELEGRAM_ADMIN_CHAT_ID"] = "999"
    s = DialogState()
    s.intent, s.service, s.branch, s.name, s.phone = "booking", "x", "y", "А", "+7 707 111 22 33"
    s.time_pref, s.step = "будни", "done"
    bot = AsyncMock()
    asyncio.run(notify_admin(bot, s, 1, "u", premium=True))
    text = bot.send_message.call_args.kwargs["text"]
    assert "<tg-emoji" in text
    # без флага — обычный текст
    s2 = DialogState()
    s2.intent, s2.service, s2.branch, s2.name, s2.phone = "booking", "x", "y", "А", "+7 707 111 22 33"
    s2.time_pref, s2.step = "будни", "done"
    bot2 = AsyncMock()
    asyncio.run(notify_admin(bot2, s2, 1, "u"))
    assert "<tg-emoji" not in bot2.send_message.call_args.kwargs["text"]
    del os.environ["TELEGRAM_ADMIN_CHAT_ID"]
