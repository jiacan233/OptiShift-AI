"""Create the workforce scheduling schema.

Revision ID: 20260916_0001
Revises:
Create Date: 2026-09-16
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260916_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employees",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("skills", sa.JSON(), nullable=False),
        sa.Column("available_days", sa.JSON(), nullable=False),
        sa.Column("leave_days", sa.JSON(), nullable=False),
        sa.Column("preferred_shift", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "system_metadata",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "schedules",
        sa.Column("schedule_id", sa.String(length=64), nullable=False),
        sa.Column("lineage_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_schedule_id", sa.String(length=64), nullable=True),
        sa.Column("base_schedule_id", sa.String(length=64), nullable=True),
        sa.Column("base_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("validation_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_schedules_version_positive"),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'cancelled')",
            name="ck_schedules_status",
        ),
        sa.ForeignKeyConstraint(["base_schedule_id"], ["schedules.schedule_id"]),
        sa.ForeignKeyConstraint(["parent_schedule_id"], ["schedules.schedule_id"]),
        sa.PrimaryKeyConstraint("schedule_id"),
    )
    op.create_index(
        "idx_schedules_lineage_version",
        "schedules",
        ["lineage_id", "version", "created_at"],
    )
    op.create_index(
        "idx_schedules_week_status",
        "schedules",
        ["week_start", "status", "version"],
    )
    op.create_table(
        "assignments",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("schedule_id", sa.String(length=64), nullable=False),
        sa.Column("employee_id", sa.String(length=32), nullable=False),
        sa.Column("day", sa.String(length=8), nullable=False),
        sa.Column("shift", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["schedule_id"], ["schedules.schedule_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "schedule_id",
            "employee_id",
            "day",
            "shift",
            name="uq_assignments_schedule_employee_day_shift",
        ),
    )
    op.create_index(
        "idx_assignments_schedule",
        "assignments",
        ["schedule_id", "day", "shift"],
    )
    metadata_table = sa.table(
        "system_metadata",
        sa.column("key", sa.String()),
        sa.column("value", sa.String()),
    )
    op.bulk_insert(
        metadata_table,
        [{"key": "employee_revision", "value": "0"}],
    )


def downgrade() -> None:
    op.drop_index("idx_assignments_schedule", table_name="assignments")
    op.drop_table("assignments")
    op.drop_index("idx_schedules_week_status", table_name="schedules")
    op.drop_index("idx_schedules_lineage_version", table_name="schedules")
    op.drop_table("schedules")
    op.drop_table("system_metadata")
    op.drop_table("employees")
