from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_slots",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("holder", sa.Text(), nullable=True),
        sa.Column("held_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("provider", "slot", name="pk_provider_slots"),
        schema="agents",
    )
    op.add_column(
        "agent_runs",
        sa.Column("cached_tokens", sa.Integer(), server_default="0", nullable=False),
        schema="agents",
    )


def downgrade() -> None:
    op.drop_column("agent_runs", "cached_tokens", schema="agents")
    op.drop_table("provider_slots", schema="agents")
