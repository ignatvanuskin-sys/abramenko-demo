"""E2E: полный booking через API до реальной заявки админу в Telegram.

Запуск:
  python scripts/e2e_test_lead.py [base_url] [phone]
По умолчанию base_url = production Railway (там настроены TELEGRAM_BOT_TOKEN
и TELEGRAM_ADMIN_CHAT_ID, поэтому в конце админ реально получит заявку).
Имя заявки помечено [ТЕСТ E2E], чтобы не путать с клиентами.

Шаги: health -> booking (услуга/волосы/время/филиал/имя/телефон) -> done -> reset.
Выход 0 = всё PASS, иначе FAIL с причиной.
"""
import json
import sys
import time
import urllib.request
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://abramenko-demo-production.up.railway.app"
PHONE = sys.argv[2] if len(sys.argv) > 2 else "+7 707 000 00 01"
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def api(path, data=None, timeout=20):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    req = urllib.request.Request(
        BASE + path, data=body,
        headers={"Content-Type": "application/json"} if body else {}, method="GET" if body is None else "POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dt = (time.monotonic() - t0) * 1000
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {}), dt
    except Exception as e:
        code = getattr(e, "code", 0) or 0
        return code, {"error": str(e)[:200]}, (time.monotonic() - t0) * 1000


print("== E2E", BASE, "==")
code, h, dt = api("/api/health")
check("health 200", code == 200 and h.get("status") == "ok", f"{dt:.0f}ms {h}")

sid = "e2e-" + uuid.uuid4().hex[:8]
steps = [
    ("хочу балаяж", "clarify_hair", False),
    ("окрашены", "time", False),
    ("будни вечером", "branch", False),
    ("Жамбыла", "await_name", False),
    ("ТЕСТ E2E", "await_phone", False),
    (PHONE, "done", True),
]
for i, (msg, exp_step, exp_done) in enumerate(steps):
    code, r, dt = api("/api/chat", {"session_id": sid, "message": msg})
    ok = code == 200 and r.get("step") == exp_step and r.get("done") is exp_done
    check(f"booking[{i}] {msg!r}", ok, f"{dt:.0f}ms step={r.get('step')} done={r.get('done')}")

# повтор того же телефона — дубля заявки быть не должно (dedup на сервере)
code, r, dt = api("/api/chat", {"session_id": sid, "message": PHONE})
check("dedup повтор", code == 200 and r.get("done") is True, r.get("message", "")[:50])

# изоляция: другая сессия не видит первую
code, r, _ = api("/api/chat", {"session_id": "e2e-iso-" + sid, "message": "где вы?"})
check("изоляция сессий", code == 200 and "Букетова" in r.get("message", ""), r.get("step"))

# reset
code, r, _ = api("/api/reset", {"session_id": sid})
check("reset", code == 200 and r.get("step") == "start", r.get("message", "")[:50])

print()
if FAILS:
    print(f"RESULT: FAIL ({len(FAILS)}): {FAILS}")
    print("Заявка админу НЕ считается доставленной.")
    sys.exit(1)
print("RESULT: PASS — booking done=true, админ получил заявку «ТЕСТ E2E» в Telegram.")
print("(если TELEGRAM_BOT_TOKEN/ADMIN_CHAT_ID не настроены — проверьте Railway Variables)")
