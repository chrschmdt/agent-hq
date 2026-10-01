from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "agent_versions",
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("digest", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("status_at", TIMESTAMP, nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("canary_pct", sa.Integer(), nullable=True),
        sa.Column("eval_summary", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'evaluated', 'canary', 'live', 'retired')", name="ck_agent_versions_status"
        ),
        sa.PrimaryKeyConstraint("version_id", name="pk_agent_versions"),
        sa.UniqueConstraint("agent", "number", name="uq_agent_versions_agent_number"),
        sa.UniqueConstraint("agent", "digest", name="uq_agent_versions_agent_digest"),
        schema="agents",
    )
    op.create_index(
        "ix_agent_versions_one_live",
        "agent_versions",
        ["agent"],
        unique=True,
        schema="agents",
        postgresql_where=sa.text("status = 'live'"),
    )
    op.create_index(
        "ix_agent_versions_one_canary",
        "agent_versions",
        ["agent"],
        unique=True,
        schema="agents",
        postgresql_where=sa.text("status = 'canary'"),
    )

    op.create_table(
        "agent_runs",
        sa.Column("work_item_id", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("finished", sa.Boolean(), nullable=False),
        sa.Column("turns", sa.Integer(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Double(), nullable=False),
        sa.Column("seconds", sa.Double(), nullable=False),
        sa.Column("approvals", sa.Integer(), nullable=False),
        sa.Column("rejected_approvals", sa.Integer(), nullable=False),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("work_item_id", "agent", name="pk_agent_runs"),
        schema="agents",
    )
    op.create_index("ix_agent_runs_version_id_updated_at", "agent_runs", ["version_id", "updated_at"], schema="agents")
    op.create_index("ix_agent_runs_agent_updated_at", "agent_runs", ["agent", "updated_at"], schema="agents")

    op.create_table(
        "agent_controls",
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.Text(), nullable=False),
        sa.Column("changed_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("agent", name="pk_agent_controls"),
        schema="agents",
    )

    op.create_table(
        "spend_daily",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("errors", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Double(), nullable=False),
        sa.PrimaryKeyConstraint("day", "agent", "model", name="pk_spend_daily"),
        schema="agents",
    )

    op.create_table(
        "model_health",
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False),
        sa.Column("open_until", TIMESTAMP, nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("model", name="pk_model_health"),
        schema="agents",
    )

    op.create_table(
        "qa_reviews",
        sa.Column("review_id", sa.Text(), nullable=False),
        sa.Column("work_item_id", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("rubric", sa.Text(), nullable=False),
        sa.Column("judge_model", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("criteria", postgresql.JSONB(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("cost_usd", sa.Double(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.PrimaryKeyConstraint("review_id", name="pk_qa_reviews"),
        sa.UniqueConstraint("work_item_id", "agent", name="uq_qa_reviews_work_item_id_agent"),
        schema="agents",
    )
    op.create_index("ix_qa_reviews_version_id_created_at", "qa_reviews", ["version_id", "created_at"], schema="agents")
    op.create_index("ix_qa_reviews_agent_created_at", "qa_reviews", ["agent", "created_at"], schema="agents")

    op.create_table(
        "qa_labels",
        sa.Column("work_item_id", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("criterion_id", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("labeled_by", sa.Text(), nullable=False),
        sa.Column("labeled_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint("verdict IN ('pass', 'fail')", name="ck_qa_labels_verdict"),
        sa.PrimaryKeyConstraint("work_item_id", "agent", "criterion_id", name="pk_qa_labels"),
        schema="agents",
    )

    op.create_table(
        "eval_runs",
        sa.Column("eval_run_id", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("candidate_id", sa.Text(), nullable=False),
        sa.Column("baseline_id", sa.Text(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("backend", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("started_at", TIMESTAMP, nullable=True),
        sa.Column("finished_at", TIMESTAMP, nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Double(), nullable=False),
        sa.CheckConstraint("status IN ('queued', 'running', 'passed', 'failed', 'error')", name="ck_eval_runs_status"),
        sa.PrimaryKeyConstraint("eval_run_id", name="pk_eval_runs"),
        schema="agents",
    )
    op.create_index("ix_eval_runs_agent_created_at", "eval_runs", ["agent", "created_at"], schema="agents")

    op.create_table(
        "eval_cases",
        sa.Column("eval_run_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("trial", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("cost_usd", sa.Double(), nullable=False),
        sa.Column("seconds", sa.Double(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["eval_run_id"],
            ["agents.eval_runs.eval_run_id"],
            name="fk_eval_cases_eval_run_id_eval_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("eval_run_id", "version_id", "case_id", "trial", name="pk_eval_cases"),
        schema="agents",
    )


def downgrade() -> None:
    op.drop_table("eval_cases", schema="agents")
    op.drop_table("eval_runs", schema="agents")
    op.drop_table("qa_labels", schema="agents")
    op.drop_table("qa_reviews", schema="agents")
    op.drop_table("model_health", schema="agents")
    op.drop_table("spend_daily", schema="agents")
    op.drop_table("agent_controls", schema="agents")
    op.drop_table("agent_runs", schema="agents")
    op.drop_table("agent_versions", schema="agents")
