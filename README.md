# Abramenko Studio — ИИ-администратор (демо)

Демо-проект строго по файлу `ПРОМПТ-агент-Abramenko-Studio.md`.

## Что внутри

- `ПРОМПТ-агент-Abramenko-Studio.md` — системный промпт (источник правды)
- `app/config.py` — филиалы, цены, контакты из 2ГИС
- `app/bot_logic.py` — rule-based диалог: ветки запись / модель / вакансия / обучение, шаги время → филиал → имя → телефон, FAQ только по фактам (единый источник истины, Telegram её не дублирует)
- `app/session_store.py` — сессии: Redis (при REDIS_URL) с in-memory fallback, переживают рестарт
- `app/tg_premium.py` — Telegram Premium-эмодзи только из таблицы владельца + `TG_PREMIUM_EMOJI_EXTRA` для новых ID без правок кода
- `app/keyboards.py` — Reply-клавиатуры под текущий шаг (услуга / время / филиал / контакт), один вопрос за сообщение
- `app/main_console.py` — консольное демо (работает без ключей)
- `app/main_telegram.py` — Telegram-транспорт (aiogram 3.x, polling, логирование, маскирование телефонов, graceful shutdown)
- `app/llm_client.py` — опциональный LLM-режим поверх того же промпта (в Telegram MVP не используется)
- `tests/test_telegram.py` — тесты сессий / записи / FAQ / ошибок
- `tests/test_logic.py` — ручной прогон сценария записи

Правила из промпта зашиты: календаря нет (окна не называем, запись не подтверждаем),
один вопрос за сообщение, имя+телефон в конце, нет выдумок про цены/услуги.

## Запуск (Windows PowerShell)

```powershell
pip install -r requirements.txt
python -m app.main_console
```

Сценарий для проверки:
1. `здравствуйте, хочу балаяж` → вопрос про волосы
2. `окрашены, был кератин` → вопрос про будни/выходные
3. `в субботу утром` → вопрос про филиал
4. `Жамбыла` → вопрос про имя
5. `Айгерим` → вопрос про телефон
6. `+7 707 123 45 67` → закрытие «Передал администратору…»

## Telegram

```powershell
Copy-Item .env.example .env
# вписать TELEGRAM_BOT_TOKEN (получить у @BotFather)
python -m app.main_telegram
```

Без токена завершается так (без traceback):

```
TELEGRAM_BOT_TOKEN is not configured
```

## .env

```
TELEGRAM_BOT_TOKEN=
OPENAI_API_KEY=        # опционально, пока не используется в Telegram MVP
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

## Тест

```powershell
python -m pytest -q
# или без pytest:
python tests/test_logic.py
```

## Сессии переживают рестарт

Диалоги хранятся persistent: Redis (если задан `REDIS_URL`) → иначе Postgres
(`DATABASE_URL`, таблица `dialog_states` в той же БД что бронирования) →
иначе in-memory. На проде уже работает Postgres-вариант — ноль новой инфраструктуры.
Проверка: `GET /api/health` → `"sessions_backend": "postgres"`.

```powershell
# локально persistent без Redis:
$env:DATABASE_URL="sqlite:///demo.db"
# опционально Redis вместо Postgres:
docker run -d -p 6379:6379 redis:7
$env:REDIS_URL="redis://localhost:6379/0"
```

## WhatsApp (Meta Cloud API)

Транспорт уже встроен (`/webhook/whatsapp`, подпись HMAC, dedup, Meta Send, retry).
Статус без секретов: `GET /api/whatsapp/status` → `configured/missing/how_to_enable`.

Что нужно от Марии для включения (прислать 5 значений):
1. `WHATSAPP_TOKEN` — permanent access token (Meta App → WhatsApp → API Setup)
2. `PHONE_NUMBER_ID` — ID номера телефона в том же окне
3. `WABA_ID` — ID WhatsApp Business Account
4. `WHATSAPP_VERIFY_TOKEN` — любая строка (придумать, вставить и в Meta, и в Railway)
5. `WHATSAPP_APP_SECRET` — Meta App → Settings → Basic → App Secret

Дальше: выставить их в Railway Variables сервиса, в Meta App в поле
Webhook URL вписать `https://abramenko-demo-production.up.railway.app/webhook/whatsapp`
и подписаться на поле `messages`. Без этих данных транспорт в standby и ничего не ломает.

## Premium-эмодзи

Таблица ID владельца — в `app/tg_premium.py` (`EMOJI_IDS`). Тексты бота используют
только эмодзи из таблицы; остальное `premium()` вычищает (правило владельца).
Новые ID без правок кода: `TG_PREMIUM_EMOJI_EXTRA="💇:<id>,📞:<id>"` в Railway Variables.
