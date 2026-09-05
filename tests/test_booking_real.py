import os
from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import Base
from app.bot_logic import DialogState, reply

def _setup_db_memory():
    from app.models import Branch, Master, Service, WorkingHours
    from datetime import time
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    br = Branch(name="Abramenko Studio", address="Букетова 61", timezone="Asia/Almaty", is_active=True)
    br2 = Branch(name="Madame", address="Жамбыла 127", timezone="Asia/Almaty", is_active=True)
    db.add_all([br, br2]); db.flush()
    m = Master(name="Анна", specialization="колорист")
    m.branches.append(br)
    db.add(m); db.flush()
    svc = Service(name="Балаяж", duration_minutes=60, price_min=25000, price_max=80000)
    db.add(svc); db.flush()
    m.services.append(svc)
    for wd in range(0,6):
        db.add(WorkingHours(master_id=m.id, weekday=wd, start_time=time(10,0), end_time=time(19,0)))
    db.commit()
    return db, br, m, svc, engine

def test_booking_with_real_slots(monkeypatch):
    monkeypatch.setenv("DEMO_BOOKING", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    db, br, m, svc, engine = _setup_db_memory()
    # need to keep same engine for bot_logic — patch _use_real_booking is already true via env
    from app.booking import get_available_slots, create_booking
    from datetime import datetime, timezone
    slots = get_available_slots(db, br.id, m.id, svc.id, date.today(), date.today()+timedelta(days=1))
    assert len(slots) >= 2
    starts = slots[0]
    appt = create_booking(db, br.id, m.id, svc.id, "Алина", "+77071234567", starts)
    db.commit()
    assert appt.id is not None
    try:
        create_booking(db, br.id, m.id, svc.id, "Боб", "+77079876543", starts)
        assert False, "should have raised"
    except ValueError as e:
        assert "занят" in str(e)
    slots2 = get_available_slots(db, br.id, m.id, svc.id, date.today(), date.today()+timedelta(days=1))
    assert starts not in slots2
    db.close()

def test_dialog_with_real_slots(monkeypatch):
    # без DEMO_BOOKING — fallback к старому flow (время)
    s = DialogState()
    r = reply(s, "хочу балаяж")
    assert "волос" in r.lower()
    r = reply(s, "окрашены")
    assert "будни" in r.lower() or "филиал" in r.lower()

def test_dialog_with_demo_booking(monkeypatch):
    # без DEMO_BOOKING — fallback к старому flow, проверяем что не ломается
    s = DialogState()
    r = reply(s, "хочу балаяж")
    assert "волос" in r.lower()
    r = reply(s, "окрашены")
    assert "филиал" in r.lower() or "будни" in r.lower()

def test_race_via_booking():
    import threading
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base
    engine = create_engine("sqlite:///test_race_demo.db", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    from app.models import Branch, Master, Service, WorkingHours
    from datetime import time
    br = Branch(name="Центр", address="ул.1", timezone="UTC", is_active=True)
    s.add(br); s.flush()
    m = Master(name="Анна", is_active=True)
    m.branches.append(br)
    s.add(m); s.flush()
    svc = Service(name="Стрижка", duration_minutes=60)
    s.add(svc); s.flush()
    m.services.append(svc)
    s.add(WorkingHours(master_id=m.id, weekday=0, start_time=time(10,0), end_time=time(18,0)))
    s.commit()
    s.close()
    from app.booking import create_booking
    from datetime import datetime, timezone
    errors = []
    def try_book():
        Session2 = sessionmaker(bind=engine)
        db = Session2()
        try:
            create_booking(db, 1, 1, 1, "Клиент", "+7000", datetime(2025,1,6,11,0, tzinfo=timezone.utc))
            db.commit()
        except ValueError as e:
            errors.append(str(e))
            db.rollback()
        finally:
            db.close()
    t1 = threading.Thread(target=try_book)
    t2 = threading.Thread(target=try_book)
    t1.start(); t2.start()
    t1.join(); t2.join()
    assert any("занят" in e for e in errors)
    import os as _os
    try:
        _os.remove("test_race_demo.db")
    except Exception:
        pass
