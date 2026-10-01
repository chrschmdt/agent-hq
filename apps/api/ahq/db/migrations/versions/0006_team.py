from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ahq_analytics_ro') THEN
                CREATE ROLE ahq_analytics_ro NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA retail, support, kpi TO ahq_analytics_ro")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA retail, support, kpi TO ahq_analytics_ro")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA retail, support, kpi GRANT SELECT ON TABLES TO ahq_analytics_ro")
    op.execute("GRANT ahq_analytics_ro TO CURRENT_USER")

    op.create_table(
        "incidents",
        sa.Column("incident_id", sa.Text(), nullable=False),
        sa.Column("work_item_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("report", postgresql.JSONB(), nullable=False),
        sa.Column("detected_at", TIMESTAMP, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high')", name="ck_incidents_severity"),
        sa.CheckConstraint("status IN ('open', 'closed')", name="ck_incidents_status"),
        sa.PrimaryKeyConstraint("incident_id", name="pk_incidents"),
        sa.UniqueConstraint("work_item_id", name="uq_incidents_work_item_id"),
        schema="agents",
    )
    op.create_index("ix_incidents_created_at", "incidents", ["created_at"], schema="agents")

    op.create_table(
        "kb_drafts",
        sa.Column("draft_id", sa.Text(), nullable=False),
        sa.Column("doc_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("published_at", TIMESTAMP, nullable=True),
        sa.CheckConstraint("status IN ('pending', 'published', 'rejected')", name="ck_kb_drafts_status"),
        sa.PrimaryKeyConstraint("draft_id", name="pk_kb_drafts"),
        schema="agents",
    )
    op.create_index("ix_kb_drafts_status", "kb_drafts", ["status"], schema="agents")

    op.create_table(
        "proposals",
        sa.Column("proposal_id", sa.Text(), nullable=False),
        sa.Column("work_item_id", sa.Text(), nullable=False),
        sa.Column("incident_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("draft_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("decided_at", TIMESTAMP, nullable=True),
        sa.CheckConstraint(
            "kind IN ('kb_article', 'policy_change', 'agent_change', 'operational')", name="ck_proposals_kind"
        ),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="ck_proposals_status"),
        sa.ForeignKeyConstraint(["incident_id"], ["agents.incidents.incident_id"], name="fk_proposals_incident_id"),
        sa.ForeignKeyConstraint(["draft_id"], ["agents.kb_drafts.draft_id"], name="fk_proposals_draft_id"),
        sa.PrimaryKeyConstraint("proposal_id", name="pk_proposals"),
        schema="agents",
    )
    op.create_index("ix_proposals_status_created_at", "proposals", ["status", "created_at"], schema="agents")

    op.add_column("work_items", sa.Column("dedupe_key", sa.Text(), nullable=True), schema="ops")
    op.create_unique_constraint("uq_work_items_dedupe_key", "work_items", ["dedupe_key"], schema="ops")
    op.add_column(
        "sim_runs",
        sa.Column("alerts_to_agents", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        schema="ops",
    )


def downgrade() -> None:
    op.drop_column("sim_runs", "alerts_to_agents", schema="ops")
    op.drop_constraint("uq_work_items_dedupe_key", "work_items", schema="ops")
    op.drop_column("work_items", "dedupe_key", schema="ops")
    op.drop_table("proposals", schema="agents")
    op.drop_table("kb_drafts", schema="agents")
    op.drop_table("incidents", schema="agents")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA retail, support, kpi REVOKE SELECT ON TABLES FROM ahq_analytics_ro")
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA retail, support, kpi FROM ahq_analytics_ro")
    op.execute("REVOKE USAGE ON SCHEMA retail, support, kpi FROM ahq_analytics_ro")
