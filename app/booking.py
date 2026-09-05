"""Бизнес-логика слотов и брони — блок 3 и 6 AGENTS.md."""
from __future__ import annotations
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from .models import Appointment, WorkingHours, ScheduleException, Service
from .models import Branch as _BranchModel  # for type hint

def _branch_tz(branch) -> ZoneInfo:
    return ZoneInfo(branch.timezone or "UTC")

def _get_working_interval(db: Session, master_id: int, day: date, tz: ZoneInfo):
    # исключения — таблица может отсутствовать в свежей демо-БД
    try:
        exc = db.execute(select(ScheduleException).where(ScheduleException.master_id==master_id, ScheduleException.date==day)).scalar_one_or_none()
    except Exception:
        db.rollback()
        exc = None
    if exc:
        if exc.is_day_off:
            return None
        if exc.custom_start and exc.custom_end:
            return (exc.custom_start, exc.custom_end)
    wh = db.execute(select(WorkingHours).where(WorkingHours.master_id==master_id, WorkingHours.weekday==day.weekday())).scalar_one_or_none()
    if not wh:
        return None
    return (wh.start_time, wh.end_time)

def get_available_slots(db: Session, branch_id: int, master_id: int, service_id: int, date_from: date, date_to: date, buffer_minutes: int = 15):
    """Возвращает список свободных стартов (datetime UTC) с учётом длительности, буфера, часов, исключений."""
    svc = db.get(Service, service_id)
    if not svc:
        raise ValueError("service not found")
    duration = timedelta(minutes=svc.duration_minutes)
    buffer_td = timedelta(minutes=buffer_minutes)
    # branch для timezone
    from .models import Branch
    branch = db.get(Branch, branch_id)
    tz = _branch_tz(branch) if branch else ZoneInfo("UTC")

    slots = []
    cur = date_from
    while cur <= date_to:
        interval = _get_working_interval(db, master_id, cur, tz)
        if interval:
            start_t, end_t = interval
            # локальное время -> UTC для сравнения с appointments
            day_start_local = datetime.combine(cur, start_t, tzinfo=tz)
            day_end_local = datetime.combine(cur, end_t, tzinfo=tz)
            day_start_utc = day_start_local.astimezone(timezone.utc)
            day_end_utc = day_end_local.astimezone(timezone.utc)

            # все booked appointments мастера в этот день (UTC) — нормализуем naive для SQLite
            appts_raw = db.execute(select(Appointment).where(
                Appointment.master_id==master_id,
                Appointment.status=="booked",
                Appointment.starts_at >= day_start_utc - duration,
                Appointment.starts_at < day_end_utc
            )).scalars().all()
            appts = []
            for a in appts_raw:
                # SQLite отдаёт naive, считаем UTC
                if a.starts_at.tzinfo is None:
                    a.starts_at = a.starts_at.replace(tzinfo=timezone.utc)
                if a.ends_at.tzinfo is None:
                    a.ends_at = a.ends_at.replace(tzinfo=timezone.utc)
                appts.append(a)

            # шаг 15 минут
            cursor = day_start_utc
            while cursor + duration <= day_end_utc:
                proposed_end = cursor + duration
                # проверка буфера: [cursor-buffer, proposed_end+buffer) не пересекается с существующими
                conflict = False
                for a in appts:
                    # с буфером
                    a_start_buf = a.starts_at - buffer_td
                    a_end_buf = a.ends_at + buffer_td
                    if not (proposed_end <= a_start_buf or cursor >= a_end_buf):
                        conflict = True
                        break
                if not conflict:
                    slots.append(cursor)
                cursor += timedelta(minutes=15)
        cur += timedelta(days=1)
    return slots

def create_booking(db: Session, branch_id: int, master_id: int, service_id: int, client_name: str, client_phone: str, starts_at: datetime):
    """Транзакционно создаёт запись. При конфликте — ошибка 'слот уже занят'."""
    svc = db.get(Service, service_id)
    if not svc:
        raise ValueError("service not found")
    ends_at = starts_at + timedelta(minutes=svc.duration_minutes)

    # защита от гонки: для Postgres — EXCLUDE, для SQLite — проверка + flush с UniqueConstraint
    # не используем with db.begin() чтобы не конфликтовать с уже открытым транзакционным контекстом в тестах
    existing = db.execute(
        select(Appointment).where(
            Appointment.master_id==master_id,
            Appointment.status=="booked",
            Appointment.starts_at < ends_at,
            Appointment.ends_at > starts_at
        ).with_for_update()
    ).scalars().all()
    if existing:
        raise ValueError("слот уже занят")

    appt = Appointment(
        branch_id=branch_id, master_id=master_id, service_id=service_id,
        client_name=client_name, client_phone=client_phone,
        starts_at=starts_at, ends_at=ends_at, status="booked", created_at=datetime.now(timezone.utc)
    )
    db.add(appt)
    try:
        db.flush()
    except Exception as e:
        db.rollback()
        if "no_overlap" in str(e) or "conflict" in str(e).lower() or "UNIQUE" in str(e) or "unique" in str(e).lower():
            raise ValueError("слот уже занят") from e
        raise
    return appt

def cancel_booking(db: Session, phone: str, booking_id: int | None = None):
    q = select(Appointment).where(Appointment.client_phone==phone, Appointment.status=="booked").order_by(Appointment.starts_at)
    if booking_id:
        q = select(Appointment).where(Appointment.id==booking_id, Appointment.client_phone==phone)
        appt = db.execute(q).scalar_one_or_none()
    else:
        appt = db.execute(q).scalars().first()
    if not appt:
        raise ValueError("активная запись не найдена")
    appt.status = "cancelled"
    db.commit()
    return appt
