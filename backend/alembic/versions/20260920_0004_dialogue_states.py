"""Versioned dialogue state; old scenarios are imported only from typed patches."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = "20260920_0004"
# Schedule compliance (20260919_0004) is the current schema predecessor;
# keeping this linear avoids requiring ``alembic upgrade heads`` in deployment.
down_revision = "20260919_0004"
branch_labels = None
depends_on = None


def upgrade():
    agent_id = sa.String(64).with_variant(mysql.VARCHAR(64, collation="utf8mb4_bin"), "mysql")
    timestamp = sa.DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")
    op.create_table(
        "conversation_dialogue_states",
        sa.Column("conversation_id", agent_id, primary_key=True),
        sa.Column("week_start", sa.Date(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", timestamp, nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.conversation_id"], ondelete="CASCADE"),
    )


def downgrade():
    op.drop_table("conversation_dialogue_states")
