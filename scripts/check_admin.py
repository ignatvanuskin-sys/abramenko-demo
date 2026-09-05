"""Диагностика доставки заявок админу. Секреты НЕ печатает — только статусы.

Запуск: railway run python scripts/check_admin.py [--send-test]
  --send-test  отправить тестовое сообщение (только если чат доступен)
"""
import os
import sys
import urllib.request
import urllib.parse
import json


def api(method, payload=None, timeout=15):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return None, "NO_TOKEN"
    data = json.dumps(payload or {}).encode() if payload is not None else None
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}", data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), "OK"
    except Exception as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        return None, f"ERR {body}"


def main():
    send_test = "--send-test" in sys.argv
    admin_id = (os.getenv("TELEGRAM_ADMIN_CHAT_ID") or "").strip()
    print("admin_chat_configured:", bool(admin_id))

    me, st = api("getMe")
    if st != "OK" or not (me or {}).get("ok"):
        print("bot_token: INVALID", st)
        return 1
    print("bot_token: VALID")

    if not admin_id:
        print("admin_chat: NOT_CONFIGURED")
        return 1
    try:
        chat_id = int(admin_id)
    except ValueError:
        print("admin_chat: BAD_FORMAT (not a number)")
        return 1

    info, st = api("getChat", {"chat_id": chat_id})
    if st == "OK" and (info or {}).get("ok"):
        print("admin_chat: REACHABLE")
    else:
        print("admin_chat:", st)
        print("DIAGNOSIS: чат не найден — админ ни разу не нажимал /start у бота.")
        print("ACTION: откройте @manager_kid_bot и нажмите /start, затем перезапустите проверку.")
        return 2

    if send_test:
        msg, st = api("sendMessage", {"chat_id": chat_id, "text": "🔔 Тест доставки заявок Abramenko Studio. Если видите это — уведомления работают."})
        if st == "OK" and (msg or {}).get("ok"):
            print("test_message: DELIVERED — проверьте Telegram")
        else:
            print("test_message:", st)
            return 3
    else:
        print("(тестовое сообщение не отправлялось; добавьте --send-test)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
