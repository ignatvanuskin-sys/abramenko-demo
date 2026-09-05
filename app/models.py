"""SQLAlchemy модели — блок 2 AGENTS.md. PostgreSQL — source of truth."""
from __future__ import annotations
import enum
from datetime import datetime, time, date
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, Time, ForeignKey, Table, UniqueConstraint, Index, text
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import ExcludeConstraint

Base = declarative_base()

# many-to-many
master_branches = Table(
    "master_branches", Base.metadata,
    Column("master_id", Integer, ForeignKey("masters.id", ondelete="CASCADE"), primary_key=True),
    Column("branch_id", Integer, ForeignKey("branches.id", ondelete="CASCADE"), primary_key=True),
)
master_services = Table(
    "master_services", Base.metadata,
    Column("master_id", Integer, ForeignKey("masters.id", ondelete="CASCADE"), primary_key=True),
    Column("service_id", Integer, ForeignKey("services.id", ondelete="CASCADE"), primary_key=True),
)

class Branch(Base):
    __tablename__ = "branches"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    address = Column(String(255), nullable=False)
    timezone = Column(String(64), nullable=False, default="Asia/Almaty")
    is_active = Column(Boolean, default=True)

class Master(Base):
    __tablename__ = "masters"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    specialization = Column(String(120))
    is_active = Column(Boolean, default=True)
    branches = relationship("Branch", secondary=master_branches, backref="masters")
    services = relationship("Service", secondary=master_services, backref="masters")

class Service(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    price_min = Column(Integer)
    price_max = Column(Integer)
    category = Column(String(64))

class WorkingHours(Base):
    __tablename__ = "working_hours"
    id = Column(Integer, primary_key=True)
    master_id = Column(Integer, ForeignKey("masters.id", ondelete="CASCADE"), nullable=False)
    weekday = Column(Integer, nullable=False)  # 0=Mon
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    __table_args__ = (UniqueConstraint("master_id", "weekday", name="uq_working_hours"),)

class ScheduleException(Base):
    __tablename__ = "schedule_exceptions"
    id = Column(Integer, primary_key=True)
    master_id = Column(Integer, ForeignKey("masters.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    is_day_off = Column(Boolean, default=False)
    custom_start = Column(Time, nullable=True)
    custom_end = Column(Time, nullable=True)
    __table_args__ = (UniqueConstraint("master_id", "date", name="uq_exception"),)

class AppointmentStatus(str, enum.Enum):
    booked = "booked"
    cancelled = "cancelled"
    completed = "completed"

class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    master_id = Column(Integer, ForeignKey("masters.id"), nullable=False)
    service_id = Column(Integer, ForeignKey("services.id"), nullable=False)
    client_name = Column(String(120), nullable=False)
    client_phone = Column(String(32), nullable=False)
    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(16), nullable=False, default=AppointmentStatus.booked.value)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_appointments_master_starts", "master_id", "starts_at"),
        UniqueConstraint("master_id", "starts_at", name="uq_master_slot"),
        # Защита от гонки: EXCLUDE работает только на Postgres, для SQLite fallback — FOR UPDATE в booking.py + UniqueConstraint
    )

# Для Postgres — отдельный DDL в миграции:
# ALTER TABLE appointments ADD CONSTRAINT no_overlap EXCLUDE USING gist (
#   master_id WITH =,
#   tsrange(starts_at, ends_at) WITH &&
# ) WHERE (status = 'booked');
