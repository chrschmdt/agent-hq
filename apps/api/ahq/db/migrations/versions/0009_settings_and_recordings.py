from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_settings"),
        schema="ops",
    )
    op.create_table(
        "recordings",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("sim_run_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("bundle", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_recordings"),
        schema="ops",
    )
    op.create_index("ix_recordings_created_at", "recordings", ["created_at"], schema="ops")


def downgrade() -> None:
    op.drop_index("ix_recordings_created_at", table_name="recordings", schema="ops")
    op.drop_table("recordings", schema="ops")
    op.drop_table("settings", schema="ops")
