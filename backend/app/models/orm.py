from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by the application and Alembic."""


class EmployeeRecord(Base):
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    skills: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    available_days: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    leave_days: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    preferred_shift: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SystemMetadataRecord(Base):
    __tablename__ = "system_metadata"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)


class ScheduleRecord(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_schedules_version_positive"),
        CheckConstraint(
            "status IN ('draft', 'confirmed', 'cancelled')",
            name="ck_schedules_status",
        ),
        Index(
            "idx_schedules_lineage_version",
            "lineage_id",
            "version",
            "created_at",
        ),
        Index(
            "idx_schedules_week_status",
            "week_start",
            "status",
            "version",
        ),
    )

    schedule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    lineage_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_schedule_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("schedules.schedule_id")
    )
    base_schedule_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("schedules.schedule_id")
    )
    base_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    validation_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AssignmentRecord(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint(
            "schedule_id",
            "employee_id",
            "day",
            "shift",
            name="uq_assignments_schedule_employee_day_shift",
        ),
        Index("idx_assignments_schedule", "schedule_id", "day", "shift"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    schedule_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("schedules.schedule_id", ondelete="CASCADE"),
        nullable=False,
    )
    employee_id: Mapped[str] = mapped_column(String(32), nullable=False)
    day: Mapped[str] = mapped_column(String(8), nullable=False)
    shift: Mapped[str] = mapped_column(String(16), nullable=False)

