from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS agents")
    op.create_table(
        "tool_calls_audit",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("work_item_id", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("approval_id", sa.Text(), nullable=True),
        sa.Column("recorded_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_tool_calls_audit"),
        schema="agents",
    )
    op.create_index(
        "ix_tool_calls_audit_work_item_id_recorded_at",
        "tool_calls_audit",
        ["work_item_id", "recorded_at"],
        schema="agents",
    )
    op.create_index("ix_tool_calls_audit_approval_id", "tool_calls_audit", ["approval_id"], schema="agents")
    op.drop_constraint("ck_tickets_source", "tickets", schema="support", type_="check")
    op.create_check_constraint(
        "ck_tickets_source", "tickets", "source IN ('history', 'simulation', 'operator')", schema="support"
    )
    op.add_column(
        "sim_runs", sa.Column("agent_tickets", sa.Integer(), nullable=False, server_default="0"), schema="ops"
    )


def downgrade() -> None:
    op.drop_column("sim_runs", "agent_tickets", schema="ops")
    op.drop_constraint("ck_tickets_source", "tickets", schema="support", type_="check")
    op.create_check_constraint("ck_tickets_source", "tickets", "source IN ('history', 'simulation')", schema="support")
    op.drop_table("tool_calls_audit", schema="agents")
    op.execute("DROP SCHEMA IF EXISTS agents")
