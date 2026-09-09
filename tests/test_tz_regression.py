import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest
from datetime import datetime
from app.bot_logic import DialogState, reply
from app.admin_notify import build_admin_message


def test_tz_slot_shown_equals_confirmed_and_admin(monkeypatch, tmp_path):
    from datetime import datetime as dt
    db = str(tmp_path / "tz_regression.db")
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
    c.commit()

    s = DialogState()
    reply(s, 'хочу балаяж')
    reply(s, 'окрашены')
    reply(s, 'Жамбыла')
    reply(s, 'Анна')
    reply(s, 'завтра')
    shown_iso = s.slots[0]
    # локальное время слота, показанное клиенту: 10:00
    shown_local = datetime.fromisoformat(shown_iso).astimezone(
        __import__('zoneinfo').ZoneInfo("Asia/Almaty")).strftime('%d.%m %H:%M')
    expected_time = shown_local.split(' ')[1]  # "10:00"

    reply(s, '1')
    reply(s, 'Тест E2E')
    client_final = reply(s, '+7 707 000 00 09')

    assert expected_time in client_final, f"TZ BUG клиенту: {client_final!r} без {expected_time}"
    assert "Вы записаны" in client_final

    admin_msg = build_admin_message(s, 1413663332, None)
    assert expected_time in admin_msg, f"TZ BUG админу: {admin_msg!r} без {expected_time}"
    assert "Подтверждённая запись" in admin_msg

    # дата в клиенте и админу совпадает
    import re
    d_client = re.search(r"(\d{2}\.\d{2})", client_final).group(1)
    d_admin = re.search(r"(\d{2}\.\d{2}) \d{4}", admin_msg).group(1)
    assert d_client == d_admin

    c.close()
    del s
    import gc
    gc.collect()
    try:
        Path(db).unlink(missing_ok=True)
    except PermissionError:
        pass  # Windows держит файл открыт — очистится tmp_path автоматически
