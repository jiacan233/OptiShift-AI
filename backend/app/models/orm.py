from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


AGENT_DATETIME = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")
AGENT_ID = String(64).with_variant(
    mysql.VARCHAR(64, collation="utf8mb4_bin"), "mysql"
)
WORKSPACE_ID = String(128).with_variant(
    mysql.VARCHAR(128, collation="utf8mb4_bin"), "mysql"
)
CLIENT_MESSAGE_ID = String(128).with_variant(
    mysql.VARCHAR(128, collation="utf8mb4_bin"), "mysql"
)


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


class ConversationRecord(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_conversations_status",
        ),
        Index(
            "idx_conversations_workspace_updated",
            "browser_workspace_id",
            "updated_at",
        ),
    )

    conversation_id: Mapped[str] = mapped_column(AGENT_ID, primary_key=True)
    browser_workspace_id: Mapped[str] = mapped_column(WORKSPACE_ID, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    active_turn_message_id: Mapped[str | None] = mapped_column(AGENT_ID)
    active_turn_owner_token: Mapped[str | None] = mapped_column(AGENT_ID)
    active_turn_started_at: Mapped[datetime | None] = mapped_column(AGENT_DATETIME)
    created_at: Mapped[datetime] = mapped_column(AGENT_DATETIME, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(AGENT_DATETIME, nullable=False)


class ConversationMessageRecord(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_conversation_messages_role",
        ),
        UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_conversation_messages_client_message",
        ),
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_conversation_messages_sequence",
        ),
        UniqueConstraint(
            "message_id",
            "conversation_id",
            name="uq_conversation_messages_message_conversation",
        ),
        Index(
            "idx_conversation_messages_conversation_created",
            "conversation_id",
            "created_at",
        ),
    )

    message_id: Mapped[str] = mapped_column(AGENT_ID, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        AGENT_ID,
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    client_message_id: Mapped[str | None] = mapped_column(CLIENT_MESSAGE_ID)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String(32))
    mutation_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    target_week: Mapped[date | None] = mapped_column(Date)
    referenced_schedule_id: Mapped[str | None] = mapped_column(String(64))
    referenced_version: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(AGENT_DATETIME, nullable=False)


class AgentToolCallRecord(Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_agent_tool_calls_status",
        ),
        Index(
            "idx_agent_tool_calls_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index("idx_agent_tool_calls_message", "message_id", "created_at"),
        UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_agent_tool_calls_sequence",
        ),
        ForeignKeyConstraint(
            ["message_id", "conversation_id"],
            [
                "conversation_messages.message_id",
                "conversation_messages.conversation_id",
            ],
            name="fk_agent_tool_calls_message_conversation",
            ondelete="CASCADE",
        ),
    )

    tool_call_id: Mapped[str] = mapped_column(AGENT_ID, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(AGENT_ID, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    message_id: Mapped[str] = mapped_column(
        AGENT_ID,
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    input_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSON
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    created_at: Mapped[datetime] = mapped_column(AGENT_DATETIME, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(AGENT_DATETIME)


class ConversationScenarioRecord(Base):
    __tablename__ = "conversation_scenarios"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "week_start", name="uq_conversation_scenarios_week"
        ),
        Index(
            "idx_conversation_scenarios_conversation_updated",
            "conversation_id",
            "updated_at",
        ),
    )

    scenario_id: Mapped[str] = mapped_column(AGENT_ID, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        AGENT_ID,
        ForeignKey("conversations.conversation_id", ondelete="CASCADE"),
        nullable=False,
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    temporary_constraints: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_strict_result: Mapped[dict | None] = mapped_column(JSON)
    last_preview_result: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(AGENT_DATETIME, nullable=False)
