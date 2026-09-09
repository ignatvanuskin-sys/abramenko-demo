"""Однократная инициализация прод-БД: миграции + demo-сид. Запускать с PROD_DB_URL в env."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

prod_url = os.getenv("PROD_DB_URL")
if not prod_url:
    print("Set PROD_DB_URL env first (public TCP proxy URL of Postgres)")
    sys.exit(1)

from sqlalchemy import create_engine, text
from app.models import Base
engine = create_engine(prod_url)

print("== Creating tables (Base.metadata) ==")
Base.metadata.create_all(engine)

# EXCLUDE constraint для Postgres
try:
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist;"))
        conn.execute(text("""
            ALTER TABLE appointments DROP CONSTRAINT IF EXISTS no_overlap;
            ALTER TABLE appointments ADD CONSTRAINT no_overlap EXCLUDE USING gist (
                master_id WITH =,
                tsrange(starts_at, ends_at) WITH &&
            ) WHERE (status = 'booked');
        """))
        conn.commit()
    print("EXCLUDE constraint: OK")
except Exception as e:
    print("EXCLUDE constraint skipped:", str(e)[:150])

# сид
print("== Seeding demo data ==")
from sqlalchemy.orm import sessionmaker
Session = sessionmaker(bind=engine)
db = Session()
from app.models import Branch, Master, Service, WorkingHours
if db.query(Branch).count() > 0:
    print("Branches already exist — skip seed (идемпотентно)")
else:
    br1 = Branch(name="Abramenko Studio", address="ул. им. Евнея Букетова, 61", timezone="Asia/Almaty", is_active=True)
    br2 = Branch(name="Madame", address="Жамбыла улица, 127", timezone="Asia/Almaty", is_active=True)
    db.add_all([br1, br2]); db.flush()
    m1 = Master(name="Анна", specialization="колорист")
    m1.branches.extend([br1, br2])
    m2 = Master(name="Мария", specialization="универсал")
    m2.branches.append(br1)
    m3 = Master(name="Игорь", specialization="барбер")
    m3.branches.append(br2)
    m4 = Master(name="Елена", specialization="колорист")
    m4.branches.append(br2)
    db.add_all([m1, m2, m3, m4]); db.flush()
    from datetime import time
    svcs = [
        Service(name="Балаяж", duration_minutes=180, price_min=25000, price_max=80000, category="окрашивание"),
        Service(name="Стрижка женская", duration_minutes=60, price_min=4000, price_max=7000, category="стрижка"),
        Service(name="Стрижка мужская", duration_minutes=30, price_min=2500, price_max=4000, category="стрижка"),
        Service(name="AirTouch", duration_minutes=240, price_min=25000, price_max=80000, category="окрашивание"),
    ]
    db.add_all(svcs); db.flush()
    for m in [m1, m2, m3, m4]:
        m.services.extend(svcs)
        for wd in range(6):
            db.add(WorkingHours(master_id=m.id, weekday=wd, start_time=time(10, 0), end_time=time(19, 0)))
    db.commit()
    print(f"Seeded: branches {br1.id}/{br2.id}, masters 4, services {len(svcs)}")

# верификация
with engine.connect() as conn:
    for t in ["branches", "masters", "services", "working_hours", "appointments"]:
        print(t, conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar())
print("== DONE ==")
