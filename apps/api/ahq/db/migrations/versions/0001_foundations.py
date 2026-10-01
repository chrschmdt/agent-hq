from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSON_EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA IF NOT EXISTS ops")

    op.execute(
        """
        CREATE TABLE ops.events (
            id bigint GENERATED ALWAYS AS IDENTITY,
            txid xid8 NOT NULL DEFAULT pg_current_xact_id(),
            kind text NOT NULL,
            occurred_at timestamptz NOT NULL,
            recorded_at timestamptz NOT NULL DEFAULT now(),
            work_item_id text,
            actor text,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT pk_events PRIMARY KEY (id)
        )
        """
    )
    op.create_index("ix_events_work_item_id_id", "events", ["work_item_id", "id"], schema="ops")

    op.create_table(
        "work_items",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=True),
        sa.Column("input", postgresql.JSONB(), server_default=JSON_EMPTY, nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_work_items"),
        sa.UniqueConstraint("thread_id", name="uq_work_items_thread_id"),
        schema="ops",
    )
    op.create_index("ix_work_items_status_created_at", "work_items", ["status", "created_at"], schema="ops")

    op.create_table(
        "approvals",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("work_item_id", sa.Text(), nullable=False),
        sa.Column("interrupt_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("decision", postgresql.JSONB(), nullable=True),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["work_item_id"], ["ops.work_items.id"], name="fk_approvals_work_item_id_work_items"),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
        sa.UniqueConstraint("work_item_id", "interrupt_id", name="uq_approvals_work_item_id_interrupt_id"),
        schema="ops",
    )
    op.create_index("ix_approvals_status_created_at", "approvals", ["status", "created_at"], schema="ops")


def downgrade() -> None:
    op.drop_table("approvals", schema="ops")
    op.drop_table("work_items", schema="ops")
    op.drop_table("events", schema="ops")
    op.execute("DROP SCHEMA IF EXISTS ops")
