"""Persist conversation scoped what-if scenarios.

Revision ID: 20260918_0003
Revises: 20260917_0002
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "20260918_0003"
down_revision: str | None = "20260917_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

agent_datetime = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")
agent_id = sa.String(length=64).with_variant(mysql.VARCHAR(length=64, collation="utf8mb4_bin"), "mysql")


def upgrade() -> None:
    op.create_table(
        "conversation_scenarios",
        sa.Column("scenario_id", agent_id, nullable=False),
        sa.Column("conversation_id", agent_id, nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("temporary_constraints", sa.JSON(), nullable=False),
        sa.Column("last_strict_result", sa.JSON(), nullable=True),
        sa.Column("last_preview_result", sa.JSON(), nullable=True),
        sa.Column("updated_at", agent_datetime, nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("scenario_id"),
        sa.UniqueConstraint("conversation_id", "week_start", name="uq_conversation_scenarios_week"),
    )
    op.create_index("idx_conversation_scenarios_conversation_updated", "conversation_scenarios", ["conversation_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("idx_conversation_scenarios_conversation_updated", table_name="conversation_scenarios")
    op.drop_table("conversation_scenarios")
