"""TZ regression: выбранный слот = подтверждение клиенту = уведомление админу (одно и то же локальное время).

Запуск: pytest tests/test_tz_regression.py -q -s
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


def test_tz_slot_shown_equals_confirmed_and_admin(monkeypatch):
    from app.bot_logic import DialogState, reply
    from app.admin_notify import build_admin_message
    from datetime import datetime
    db = str(Path(__file__).resolve().parent / "tz_regression.db")
    pathlib_db = Path(db)
    pathlib_db.unlink(missing_ok=True)
    monkeypatch.setenv("DEMO_BOOKING", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db)
    import sqlite3
    c = sqlite3.connect(db)
    c.executescript("""
    CREATE TABLE branches (id INTEGER PRIMARY KEY, name TEXT, address TEXT, timezone TEXT, is_active INTEGER);
    INSERT INTO branches VALUES (1, 'Abramenko Studio', 'Букетова 61', 'Asia/Almaty', 1);
    CREATE TABLE masters (id INTEGER PRIMARY KEY, name TEXT, specialization TEXT, is_active INTEGER);
    INSERT INTO masters VALUES (1, 'Анна', 'колорист', 1);
    CREATE TABLE services (id INTEGER PRIMARY KEY, name TEXT, duration_minutes INTEGER, price_min INTEGER, price_max INTEGER, category TEXT);
    INSERT INTO services VALUES (1, 'Балаяж', 60, 25000, 80000, 'окрашивание');
    CREATE TABLE master_branches (master_id INTEGER, branch_id INTEGER);
    INSERT INTO master_branches VALUES (1, 1);
    CREATE TABLE master_services (master_id INTEGER, service_id INTEGER);
    INSERT INTO master_services VALUES (1, 1);
    CREATE TABLE working_hours (id INTEGER PRIMARY KEY, master_id INTEGER, weekday INTEGER, start_time TEXT, end_time TEXT);
    CREATE TABLE schedule_exceptions (id INTEGER PRIMARY KEY, master_id INTEGER, date TEXT, is_day_off INTEGER, custom_start TEXT, custom_end TEXT);
    CREATE TABLE appointments (id INTEGER PRIMARY KEY, branch_id INTEGER, master_id INTEGER, service_id INTEGER, client_name TEXT, client_phone TEXT, starts_at TEXT, ends_at TEXT, status TEXT DEFAULT 'booked', created_at TEXT);
    """)
    for wd in range(6):
        c.execute("INSERT INTO working_hours VALUES (%d, 1, %d, '10:00', '19:00')" % (wd+1, wd))
    c.commit(); c.close()

    s = DialogState()
    reply(s, 'хочу балаяж')
    reply(s, 'окрашены')
    reply(s, 'Жамбыла')
    reply(s, 'Анна')
    reply(s, 'завтра')
    shown_time = s.slots[0]
    expected_local = datetime.fromisoformat(shown_time).strftime('%d.%m %H:%M')

    reply(s, '1')
    reply(s, 'Тест E2E')
    client_final = reply(s, '+7 707 000 00 09')

    assert expected_local in client_final, f"TZ BUG клиенту: {client_final!r} без {expected_local}"
    assert "Вы записаны" in client_final

    admin_msg = build_admin_message(s, 1413663332, None)
    assert "07.09 2026 10:00" in admin_msg, f"TZ BUG админу: {admin_msg!r}"
    assert "Подтверждённая запись" in admin_msg
    import gc
    c.close()
    del s
    gc.collect()
    try:
        pathlib_db.unlink(missing_ok=True)
    except PermissionError:
        pass  # Windows может держать файл — не критично
