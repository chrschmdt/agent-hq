from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "sim_runs",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("scenario", sa.Text(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", TIMESTAMP, nullable=False),
        sa.Column("ends_at", TIMESTAMP, nullable=False),
        sa.Column("sim_now", TIMESTAMP, nullable=False),
        sa.Column("tick_no", sa.Integer(), nullable=False),
        sa.Column("tick_minutes", sa.Integer(), nullable=False),
        sa.Column("tick_seconds", sa.Double(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint("status IN ('running', 'paused', 'finished', 'stopped')", name="ck_sim_runs_status"),
        sa.PrimaryKeyConstraint("run_id", name="pk_sim_runs"),
        schema="ops",
    )
    op.create_index("ix_sim_runs_created_at", "sim_runs", ["created_at"], schema="ops")

    op.create_table(
        "sim_script",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("due_at", TIMESTAMP, nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["ops.sim_runs.run_id"], name="fk_sim_script_run_id_sim_runs"),
        sa.PrimaryKeyConstraint("run_id", "seq", name="pk_sim_script"),
        schema="ops",
    )
    op.create_index("ix_sim_script_run_id_due_at", "sim_script", ["run_id", "due_at"], schema="ops")


def downgrade() -> None:
    op.drop_table("sim_script", schema="ops")
    op.drop_table("sim_runs", schema="ops")
