"""Add persistent agent conversations, messages, and tool traces.

Revision ID: 20260917_0002
Revises: 20260916_0001
Create Date: 2026-09-17
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = "20260917_0002"
down_revision: str | None = "20260916_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


agent_datetime = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6), "mysql"
)
agent_id = sa.String(length=64).with_variant(
    mysql.VARCHAR(length=64, collation="utf8mb4_bin"), "mysql"
)
workspace_id = sa.String(length=128).with_variant(
    mysql.VARCHAR(length=128, collation="utf8mb4_bin"), "mysql"
)
client_message_id = sa.String(length=128).with_variant(
    mysql.VARCHAR(length=128, collation="utf8mb4_bin"), "mysql"
)


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("conversation_id", agent_id, nullable=False),
        sa.Column("browser_workspace_id", workspace_id, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("active_turn_message_id", agent_id, nullable=True),
        sa.Column("active_turn_owner_token", agent_id, nullable=True),
        sa.Column("active_turn_started_at", agent_datetime, nullable=True),
        sa.Column("created_at", agent_datetime, nullable=False),
        sa.Column("updated_at", agent_datetime, nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_conversations_status",
        ),
        sa.PrimaryKeyConstraint("conversation_id"),
    )
    op.create_index(
        "idx_conversations_workspace_updated",
        "conversations",
        ["browser_workspace_id", "updated_at"],
    )

    op.create_table(
        "conversation_messages",
        sa.Column("message_id", agent_id, nullable=False),
        sa.Column("conversation_id", agent_id, nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("client_message_id", client_message_id, nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=32), nullable=True),
        sa.Column(
            "mutation_requested",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("target_week", sa.Date(), nullable=True),
        sa.Column("referenced_schedule_id", sa.String(length=64), nullable=True),
        sa.Column("referenced_version", sa.Integer(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", agent_datetime, nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_conversation_messages_role",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.conversation_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("message_id"),
        sa.UniqueConstraint(
            "conversation_id",
            "client_message_id",
            name="uq_conversation_messages_client_message",
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_conversation_messages_sequence",
        ),
        sa.UniqueConstraint(
            "message_id",
            "conversation_id",
            name="uq_conversation_messages_message_conversation",
        ),
    )
    op.create_index(
        "idx_conversation_messages_conversation_created",
        "conversation_messages",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "agent_tool_calls",
        sa.Column("tool_call_id", agent_id, nullable=False),
        sa.Column("conversation_id", agent_id, nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("message_id", agent_id, nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", agent_datetime, nullable=False),
        sa.Column("finished_at", agent_datetime, nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_agent_tool_calls_status",
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "conversation_id"],
            [
                "conversation_messages.message_id",
                "conversation_messages.conversation_id",
            ],
            name="fk_agent_tool_calls_message_conversation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tool_call_id"),
        sa.UniqueConstraint(
            "conversation_id",
            "sequence_number",
            name="uq_agent_tool_calls_sequence",
        ),
    )
    op.create_index(
        "idx_agent_tool_calls_conversation_created",
        "agent_tool_calls",
        ["conversation_id", "created_at"],
    )
    op.create_index(
        "idx_agent_tool_calls_message",
        "agent_tool_calls",
        ["message_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_tool_calls_message", table_name="agent_tool_calls")
    op.drop_index(
        "idx_agent_tool_calls_conversation_created", table_name="agent_tool_calls"
    )
    op.drop_table("agent_tool_calls")
    op.drop_index(
        "idx_conversation_messages_conversation_created",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    op.drop_index(
        "idx_conversations_workspace_updated", table_name="conversations"
    )
    op.drop_table("conversations")
