import os
os.environ['DEMO_BOOKING'] = '1'
os.environ['DATABASE_URL'] = 'sqlite:///C:/TGOD/абраменко-демо/db_check.db'
import sqlite3
c = sqlite3.connect('C:/TGOD/абраменко-демо/db_check.db')
c.executescript("""
DROP TABLE IF EXISTS appointments;
DROP TABLE IF EXISTS schedule_exceptions;
CREATE TABLE schedule_exceptions (id INTEGER PRIMARY KEY, master_id INTEGER, date TEXT, is_day_off INTEGER, custom_start TEXT, custom_end TEXT);
""")
c.execute("""CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY, branch_id INTEGER, master_id INTEGER, service_id INTEGER,
    client_name TEXT, client_phone TEXT, starts_at TEXT, ends_at TEXT,
    status TEXT DEFAULT 'booked', created_at TEXT)""")
c.commit(); c.close()
from app.bot_logic import DialogState, reply
s = DialogState()
reply(s, 'хочу балаяж'); reply(s, 'окрашены')
r1 = reply(s, 'Жамбыла')
print('1:', r1[:100])
r2 = reply(s, 'завтра')
print('2:', r2[:140])
r3 = reply(s, '1')
print('3:', r3[:80], '| step:', s.step)
r4 = reply(s, 'Тест Клиент')
print('4:', r4[:80], '| step:', s.step)
r5 = reply(s, '+7 707 000 00 09')
print('5:', r5[:100], '| step:', s.step, '| slot:', s.selected_slot)
import sqlite3
chk = sqlite3.connect('C:/TGOD/абраменко-демо/db_check.db')
print('appointments:', chk.execute("SELECT COUNT(*) FROM appointments WHERE status='booked'").fetchone()[0])
