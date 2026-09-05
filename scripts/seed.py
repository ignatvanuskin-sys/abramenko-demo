# DEMO DATA — заменить на реальное расписание перед продакшеном
"""Демо-данные под заполнение блока 9 AGENTS.md. Запускать после alembic upgrade head."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
from app.models import Base, Branch, Master, Service, WorkingHours
from app.config import PRICES
from datetime import time

load_dotenv()
engine = create_engine(os.getenv("DATABASE_URL", "sqlite:///demo.db"))
Session = sessionmaker(bind=engine)
db = Session()

# очистка для идемпотентности демо
try:
    db.query(WorkingHours).delete()
    for tbl in ["master_services", "master_branches"]:
        db.execute(__import__("sqlalchemy").text(f"DELETE FROM {tbl}"))
    db.query(Service).delete()
    db.query(Master).delete()
    db.query(Branch).delete()
    db.commit()
except Exception:
    db.rollback()

# 2 филиала — как в реальном Abramenko Studio (DEMO DATA)
br1 = Branch(name="Abramenko Studio", address="ул. им. Евнея Букетова, 61", timezone="Asia/Almaty", is_active=True)
br2 = Branch(name="Madame", address="Жамбыла улица, 127", timezone="Asia/Almaty", is_active=True)
db.add_all([br1, br2]); db.flush()

# мастера — по 2 на филиал (DEMO DATA — заменить на реальное расписание перед продакшеном)
m1 = Master(name="Анна", specialization="колорист")
m1.branches.extend([br1, br2])
m2 = Master(name="Мария", specialization="универсал")
m2.branches.append(br1)
m3 = Master(name="Игорь", specialization="барбер")
m3.branches.append(br2)
m4 = Master(name="Елена", specialization="колорист")
m4.branches.append(br2)
db.add_all([m1,m2,m3,m4]); db.flush()

# услуги — из app/config.py PRICES (реальные цены, менять не нужно) + базовые
services = []
for name, price_str in PRICES.items():
    import re
    m = re.search(r"(\d[\d\s]*)", price_str)
    price = int(m.group(1).replace(" ", "").replace("\xa0","")) if m else 10000
    svc = Service(name=name, duration_minutes=60 if "стрижк" in name else 180, price_min=price, price_max=price+20000, category="demo")
    services.append(svc)
base_services = [
    Service(name="Балаяж", duration_minutes=180, price_min=25000, price_max=80000, category="окрашивание"),
    Service(name="Стрижка женская", duration_minutes=60, price_min=4000, price_max=7000, category="стрижка"),
    Service(name="Стрижка мужская", duration_minutes=30, price_min=2500, price_max=4000, category="стрижка"),
    Service(name="AirTouch", duration_minutes=240, price_min=25000, price_max=80000, category="окрашивание"),
]
db.add_all(services + base_services); db.flush()
for m in [m1,m2,m3,m4]:
    m.services.extend(base_services + services[:2])

# часы: Пн–Сб 10:00–19:00 (DEMO DATA)
for m in [m1,m2,m3,m4]:
    for wd in range(0,6):
        db.add(WorkingHours(master_id=m.id, weekday=wd, start_time=time(10,0), end_time=time(19,0)))

db.commit()
print(f"seed done (DEMO DATA): branches {br1.id}/{br2.id} masters {[m1.id, m2.id, m3.id, m4.id]} services {len(services+base_services)}")
print("DEMO DATA — заменить на реальное расписание перед продакшеном")
