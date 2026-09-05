"""Booking tools — OpenAI/Groq function calling. Переписано из gemini_tools.py для Groq/OpenAI.

Одна схема tools=[{type: "function", function: {...}}] работает и на Groq, и на OpenAI.
"""
from __future__ import annotations
from datetime import date
from typing import List, Optional
from sqlalchemy.orm import Session

def get_branches(db: Session):
    from .models import Branch
    return [{"id": b.id, "name": b.name, "address": b.address, "timezone": b.timezone} for b in db.query(Branch).filter_by(is_active=True).all()]

def get_services(db: Session, branch_id: Optional[int]=None):
    from .models import Service
    return [{"id": s.id, "name": s.name, "duration": s.duration_minutes, "price_min": s.price_min, "price_max": s.price_max, "category": s.category} for s in db.query(Service).all()]

def get_masters(db: Session, branch_id: int, service_id: int):
    from .models import Master
    q = db.query(Master).filter(Master.is_active==True).all()
    res = []
    for m in q:
        if not any(b.id==branch_id for b in m.branches):
            continue
        if not any(s.id==service_id for s in m.services):
            continue
        res.append({"id": m.id, "name": m.name, "specialization": m.specialization})
    return res

def get_available_slots(db: Session, branch_id: int, master_id: int, service_id: int, date_from: date, date_to: date):
    from .booking import get_available_slots as _slots
    import os
    buf = int(os.getenv("BUFFER_MINUTES", "15"))
    slots = _slots(db, branch_id, master_id, service_id, date_from, date_to, buffer_minutes=buf)
    return [s.isoformat() for s in slots]

def create_booking(db: Session, branch_id: int, master_id: int, service_id: int, client_name: str, client_phone: str, starts_at: str):
    from .booking import create_booking as _create
    from dateutil.parser import isoparse
    from datetime import timezone
    dt = isoparse(starts_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    appt = _create(db, branch_id, master_id, service_id, client_name, client_phone, dt)
    db.commit()
    try:
        from .admin_notify import notify_admin_booking
        # notify will be called from dialog layer, not here
        pass
    except Exception:
        pass
    return {"id": appt.id, "starts_at": appt.starts_at.isoformat(), "ends_at": appt.ends_at.isoformat(), "status": appt.status}

def cancel_booking(db: Session, phone: str, booking_id: Optional[int]=None):
    from .booking import cancel_booking as _cancel
    appt = _cancel(db, phone, booking_id)
    return {"id": appt.id, "status": appt.status}

# OpenAI-style tools (Groq и OpenAI — одна схема)
BOOKING_TOOLS = [
    {"type": "function", "function": {"name": "get_branches", "description": "Список филиалов", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "get_services", "description": "Услуги с ценами и длительностью", "parameters": {"type": "object", "properties": {"branch_id": {"type": "integer"}}, "required": []}}},
    {"type": "function", "function": {"name": "get_masters", "description": "Мастера в филиале для услуги", "parameters": {"type": "object", "properties": {"branch_id": {"type": "integer"}, "service_id": {"type": "integer"}}, "required": ["branch_id", "service_id"]}}},
    {"type": "function", "function": {"name": "get_available_slots", "description": "Свободные слоты мастера с учётом часов и буфера", "parameters": {"type": "object", "properties": {"branch_id": {"type": "integer"}, "master_id": {"type": "integer"}, "service_id": {"type": "integer"}, "date_from": {"type": "string", "format": "date"}, "date_to": {"type": "string", "format": "date"}}, "required": ["branch_id","master_id","service_id","date_from","date_to"]}}},
    {"type": "function", "function": {"name": "create_booking", "description": "Создать запись транзакционно, при конфликте вернёт ошибку слот уже занят", "parameters": {"type": "object", "properties": {"branch_id": {"type": "integer"}, "master_id": {"type": "integer"}, "service_id": {"type": "integer"}, "client_name": {"type": "string"}, "client_phone": {"type": "string"}, "starts_at": {"type": "string", "description": "ISO8601 UTC"}}, "required": ["branch_id","master_id","service_id","client_name","client_phone","starts_at"]}}},
    {"type": "function", "function": {"name": "cancel_booking", "description": "Отменить запись по телефону", "parameters": {"type": "object", "properties": {"phone": {"type": "string"}, "booking_id": {"type": "integer"}}, "required": ["phone"]}}},
]
