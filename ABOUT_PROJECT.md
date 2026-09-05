# Abramenko Studio — ИИ-администратор: от А до Я

> Один `bot_logic` — три транспорта: **Web Demo**, **Telegram**, **WhatsApp (Meta Cloud API)**. Проект для демонстрации клиентам, как ИИ-администратор забирает рутину у живого админа.

---

## 1. Зачем проект

Салон в Петропавловске теряет заявки в WhatsApp/Instagram: админ не успевает отвечать на «сколько стоит балаяж?», «где вы?», «есть ли окна в субботу?». Бот нужен чтобы:

- отвечать на типовые вопросы по фактам из 2ГИС без ожидания;
- вести по короткому сценарию записи и забирать `имя + телефон`;
- отдавать **готовую заявку** (не сырые вопросы) админу в Telegram;
- показывать клиенту на сайте живой **WhatsApp-демо** — «пишу как в WhatsApp».

Сейчас это **MVP без календаря** — бот не называет слоты `10:00/12:30`, спрашивает предпочтение `будни/выходные утро/вечер`, а админ перезванивает. Архитектура уже готова к реальным слотам (см. §11).

---

## 2. Что такое Abramenko Studio (факты из 2ГИС)

**Сеть 1 → 2 точки, бренд один.**

| Филиал | Адрес | Ориентир | Рейтинг | Особенность |
|---|---|---|---|---|
| **Abramenko Studio** | Букетова 61 | Евразийский рынок 200м | 4.6 ★ 170 | брови/лазер, 3 телефона |
| **Madame** | Жамбыла 127 | Конституции Казахстана 80м | 4.8 ★ 191 + **Премия 2ГИС 2025** + парковка 7 | свадебные причёски/муж. маникюр, 1 телефон |

Общее: слоган `Окрашивание и стрижки любой сложности`, прайс один (AirTouch/балаяж/dim-out/мелирование 25–80k, total blond 25–70k, коррекция 15–28k, один тон от 8k, выход из тёмного 35–130k, жен стрижка 4–7k / Madame от 5000, муж 2.5–4k / от 3500 — остальное «уточню у администратора»), оплата карта/наличные/перевод, Wi-Fi, запись по предзаписи, `@studio_abramenkomariia`, `+7 707 486 54 37`.

Источник правды: `ПРОМПТ-агент-Abramenko-Studio.md` + `app/config.py` (branches, PRICES, SALON). Бот никогда не выдумывает цены/адреса/мастеров.

---

## 3. Что делает бот

**4 ветки + FAQ + off-topic:**

- **booking** `услуга → состояние волос (окрашены/свой) → время (будни/выходные утро/вечер) → филиал → имя → телефон → done`. Имя/телефон всегда в конце, календарь не подключён — окна не называет.
- **model** `процедура → волосы → готовы на длительную + фото → имя → телефон`
- **vacancy** `специализация (парикмахер/ногти/брови) → портфолио → имя → телефон`
- **training** `направление → релевантность → опыт → имя → телефон` — если `программирование/Python/английский/повар` → `Поняла 😊 Обучение … у нас не проводится` без сбора лида
- **FAQ** строго по филиалу: `где вы?` → обе точки, `что на Жамбыла?` → только Madame, `делаете брови?` → Букетова 61 + уточню на Жамбыла, `мужской маникюр/свадебные` → Жамбыла
- **off_topic** `как поступить в вуз / расскажи про Python / какая погода` → `Поняла 😊 Я могу помочь только по вопросам Abramenko Studio...` без смены `DialogState` и без лида
- При `done` → одна заявка админу в Telegram (`is_booking_complete` по полям, dedup `_admin_notified`).

Правила тона: `Сначала ответь. Потом один вопрос.` Коротко 1-2 строки, без канцелярита, без «дорогая», максимум один смайл, не извиняться трижды, не говорить про CRM.

---

## 4. Как делает — архитектура

```
                ┌─ Web Demo ─┐
                │ Telegram   │──┐
WhatsApp ──► Meta Webhook ──┼──┴──► wa_id / session_id / user_id
                │            │      ↓
                │            │   DialogState (intent/service/hair/time/branch/name/phone/step)
                │            │      ↓
                └────────────┘   bot_logic.reply(state, text)  ← transport-independent
                                     ↓ (facts → intent → LLM fallback → safe)
                                  is_booking_complete?
                                     ↓ done
                                  admin_notify.notify_admin → Telegram
```

- `bot_logic.reply(state, text)` — единственная бизнес-логика, принимает `str` и мутирует `DialogState`, возвращает `str`. Не знает про HTTP/Telegram/WhatsApp.
- `session_store` — `InMemorySessionStore` per `wa_id`/`user_id`/`UUID`, интерфейс `get/reset` → легко заменить на Redis/Postgres.
- `llm_client` — provider abstraction `LLM_PROVIDER=groq` `LLM_MODEL=openai/gpt-oss-120b` (1000 tok/s, 0.71s TTFT, $0.15/$0.60) + fallback `openai/gpt-4o-mini`, `temperature 0.2`, `max 180`, `timeout 5s`, 6 сообщений контекст, short prompt для Groq TPM 8k, `classify_on_topic` для off_topic. Без ключа — deterministic-only.
- `whatsapp.py` — тонкий транспорт: `GET /webhook/whatsapp` (hub.mode/verify_token/challenge), `POST /webhook/whatsapp` (HMAC `X-Hub-Signature-256` fail-closed, parse `entry.changes.value.messages[].from/id/text.body`, dedup по `message_id`, `BackgroundTasks` → 200 ACK → `reply()` → Meta Send `POST https://graph.facebook.com/{v}/ {PHONE_ID}/messages` + `notify_admin`).
- `web_api.py` — `POST /api/chat`/`/api/reset`/`GET /api/health` + static `web/`, тоже вызывает `reply`.
- `main_telegram.py` — `aiogram 3.x` polling, `keyboard_for_step`, маскирование телефона, `compare_digest` нет (Telegram свой).

---

## 5. Стек

`Python 3.11`, `FastAPI`, `uvicorn`, `aiogram`, `openai`, `pydantic`, `httpx`, `python-dotenv`, `SQLAlchemy` (для будущего календаря), `pytest`, `Railway` (Postgres plugin — источник правды для слотов, Alembic, `railway.json` `uvicorn app:app` / `python -m app.main` combined, health `/health`→`/api/health`).

---

## 6. Структура репо

```
app.py                  # (beauty-booking-bot шаблон) FastAPI + Gemini tools, /webhook/whatsapp + /health
models.py               # Branch/Master/Service/WorkingHours/ScheduleException/Appointment + EXCLUDE
booking.py              # get_available_slots (буфер 15м, TZ Asia/Almaty) + create_booking (SELECT FOR UPDATE)
gemini_tools.py         # 6 функций (get_branches, get_services, get_masters, get_available_slots, create_booking, cancel_booking)
adapters/               # base.py send_message/parse_incoming, meta.py, green_api.py
app/bot_logic.py        # DialogState + reply
app/session_store.py    # InMemorySessionStore
app/llm_client.py       # provider abstraction + failover
app/admin_notify.py     # is_booking_complete, build_admin_message (🔔), notify_admin dedup
app/web_api.py          # /api/chat, /reset, /health + static
app/whatsapp.py         # /webhook/whatsapp GET/POST, verify, wa_id session, dedup, Meta send
app/main.py             # combined: uvicorn web_api + telegram polling
app/main_telegram.py    # polling
app/keyboards.py        # ReplyKeyboard per step
web/index.html|styles.css|app.js # WhatsApp-like phone 360×700, notch, header, bubbles, typing, quick replies, success
migrations/             # Alembic + EXCLUDE
scripts/seed.py         # демо-филиал/мастера/услуги/часы
tests/                  # test_telegram, test_admin, test_web, test_branches_llm, test_llm_whatsapp, test_off_topic, test_training_fix, test_whatsapp_transport
railway.json            # startCommand python -m app.main
.env.example            # TELEGRAM_*, LLM_*, WHATSAPP_*, GROQ_API_KEY
```

---

## 7. Логика филиалов

Не смешивать. `где вы?` → обе с рейтингами/ориентирами/парковкой + `Какой филиал вам удобнее?`. `что на Жамбыла?` → только Madame. `брови/лазер` → Букетова 61, `мужской маникюр/свадебные` → Жамбыла. Один вопрос за сообщение.

---

## 8. LLM

Groq `openai/gpt-oss-120b` primary (выбран после сравнения Groq 1000 tok/s vs OpenAI 82 tok/s vs Gemini deprecated vs Claude дорого), fallback OpenAI. Используется только когда `faq is None && intent is None && не в booking flow`, не меняет `DialogState`, не выбирает цену/филиал/окно, не подтверждает запись. При `GROQ_API_KEY` отсутствует — deterministic `Уточню`.

---

## 9. Безопасность

`X-Hub-Signature-256` HMAC `compare_digest` fail-closed, секреты только в `Railway Variables` (не в Git/frontend/logs/Telegram), `html.escape` + `textContent` vs XSS, телефон маскируется `+7 707 123****`, `system prompt` не отдаётся.

---

## 10. Тесты

`pytest -q` → `122 passed` (было 101): `test_telegram` 15, `test_admin` 9, `test_web` 13, `test_branches_llm` 23, `test_llm_whatsapp` 15, `test_off_topic` 17, `test_training_fix` 9, `test_whatsapp_transport` 21. Плюс `beauty-booking-bot` 7 (slots, race `слот уже занят`, hardening).

---

## 11. Деплой Railway

`beauty-booking-bot` и `абраменко-демо` — один проект `resourceful-integrity` (Postgres plugin), два сервиса. `abramenko-demo` → `https://abramenko-demo-production.up.railway.app` (`/health` 200, `/api/chat`, `/webhook/whatsapp`), `beauty-booking-bot` → `https://beauty-booking-bot-production-ab3d.up.railway.app`. Build `Railpack 0.39`, `python 3.11.16`, `pip install -r requirements.txt`, health `/health`.

Переменные: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID`, `LLM_PROVIDER=groq`, `LLM_MODEL=openai/gpt-oss-120b`, `GROQ_API_KEY`, `WHATSAPP_TOKEN`, `PHONE_NUMBER_ID`, `WABA_ID`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `GRAPH_API_VERSION=v21.0`, `DATABASE_URL=${{Postgres.DATABASE_URL}}`.

---

## 12. Локальный запуск

```powershell
pip install -r requirements.txt
copy .env.example .env  # заполни TELEGRAM_* и GROQ_API_KEY
python -m app.main_console  # консоль демо
python -m app.main          # web 8000 + telegram polling
# web: http://localhost:8000/  — пиши "привт хочу балаяж" без кнопок
pytest -q
```

---

## 13. Что дальше

Без переписывания `bot_logic`: подключить реальный WhatsApp Business (владелец даёт `WABA_ID`, `PHONE_NUMBER_ID`, `Access Token`, `App Secret`, `Verify Token`), затем заменить предпочтение `будни/выходные` на реальные слоты `10:00 12:30` через `Postgres` + `get_available_slots`/`create_booking` + Gemini tools (уже есть в `beauty-booking-bot`).

---

## 14. Статус

`Web Demo: READY`, `Backend bot_logic: READY`, `Real WhatsApp transport: PASS` (122/122), `Real booking slots: NOT IMPLEMENTED` (архитектура готова в `beauty-booking-bot`), `Telegram admin: READY`.

Следующий шаг после аудита — `Meta WhatsApp Cloud API` к уже готовому `reply()`.
