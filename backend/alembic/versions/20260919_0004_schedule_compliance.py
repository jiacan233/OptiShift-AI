"""Persist schedule compliance independently from lifecycle status.

Revision ID: 20260919_0004
Revises: 20260918_0003
Create Date: 2026-09-19
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260919_0004"
down_revision: str | None = "20260918_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schedules",
        sa.Column(
            "compliance_status",
            sa.String(length=32),
            nullable=False,
            server_default="invalid",
        ),
    )
    schedules = sa.table("schedules", sa.column("validation_json", sa.JSON), sa.column("compliance_status", sa.String))
    op.execute(schedules.update().where(
        schedules.c.validation_json["passed"].as_boolean() == sa.true()
    ).values(compliance_status="compliant"))


def downgrade() -> None:
    op.drop_column("schedules", "compliance_status")
