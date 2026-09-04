# Abramenko Studio — ИИ-администратор (демо)

Демо-проект строго по файлу `ПРОМПТ-агент-Abramenko-Studio.md`.

## Что внутри

- `ПРОМПТ-агент-Abramenko-Studio.md` — системный промпт (источник правды)
- `app/config.py` — филиалы, цены, контакты из 2ГИС
- `app/bot_logic.py` — rule-based диалог: ветки запись / модель / вакансия / обучение, шаги время → филиал → имя → телефон, FAQ только по фактам (единый источник истины, Telegram её не дублирует)
- `app/session_store.py` — in-memory сессии по user_id, интерфейс для замены на Redis/PG без правок логики
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
