from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

EMBEDDING = Vector(1024)
TIMESTAMP = sa.DateTime(timezone=True)


def _hnsw(table: str, schema: str) -> None:
    op.create_index(
        f"ix_{table}_embedding_hnsw",
        table,
        ["embedding"],
        schema=schema,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS support")
    op.execute("CREATE SCHEMA IF NOT EXISTS kpi")

    op.add_column("orders", sa.Column("placed_at", TIMESTAMP, nullable=True), schema="retail")

    op.create_table(
        "shipments",
        sa.Column("tracking_id", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("carrier", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("shipped_at", TIMESTAMP, nullable=True),
        sa.Column("promised_at", TIMESTAMP, nullable=True),
        sa.Column("delivered_at", TIMESTAMP, nullable=True),
        sa.CheckConstraint(
            "status IN ('label_created', 'in_transit', 'delivered', 'cancelled')", name="ck_shipments_status"
        ),
        sa.ForeignKeyConstraint(["order_id"], ["retail.orders.order_id"], name="fk_shipments_order_id_orders"),
        sa.PrimaryKeyConstraint("tracking_id", name="pk_shipments"),
        schema="retail",
    )
    op.create_index("ix_shipments_order_id", "shipments", ["order_id"], schema="retail")
    op.create_index("ix_shipments_carrier_shipped_at", "shipments", ["carrier", "shipped_at"], schema="retail")
    op.create_index("ix_shipments_region_shipped_at", "shipments", ["region", "shipped_at"], schema="retail")
    op.create_index("ix_shipments_status", "shipments", ["status"], schema="retail")

    op.create_table(
        "refunds",
        sa.Column("refund_id", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("amount", sa.Double(), nullable=False),
        sa.Column("payment_method_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["retail.orders.order_id"], name="fk_refunds_order_id_orders"),
        sa.ForeignKeyConstraint(
            ["payment_method_id"], ["retail.payment_methods.id"], name="fk_refunds_payment_method_id_payment_methods"
        ),
        sa.PrimaryKeyConstraint("refund_id", name="pk_refunds"),
        schema="retail",
    )
    op.create_index("ix_refunds_order_id", "refunds", ["order_id"], schema="retail")
    op.create_index("ix_refunds_created_at", "refunds", ["created_at"], schema="retail")

    op.create_table(
        "reviews",
        sa.Column("review_id", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("embedding", EMBEDDING, nullable=True),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating"),
        sa.ForeignKeyConstraint(["product_id"], ["retail.products.product_id"], name="fk_reviews_product_id_products"),
        sa.ForeignKeyConstraint(
            ["item_id"], ["retail.product_variants.item_id"], name="fk_reviews_item_id_product_variants"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["retail.customers.user_id"], name="fk_reviews_user_id_customers"),
        sa.PrimaryKeyConstraint("review_id", name="pk_reviews"),
        schema="retail",
    )
    op.create_index("ix_reviews_product_id_created_at", "reviews", ["product_id", "created_at"], schema="retail")
    op.create_index("ix_reviews_item_id", "reviews", ["item_id"], schema="retail")
    _hnsw("reviews", "retail")

    op.create_table(
        "tickets",
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("product_id", sa.Text(), nullable=True),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("resolved_at", TIMESTAMP, nullable=True),
        sa.Column("csat", sa.SmallInteger(), nullable=True),
        sa.CheckConstraint("status IN ('open', 'waiting_customer', 'resolved', 'escalated')", name="ck_tickets_status"),
        sa.CheckConstraint("source IN ('history', 'simulation')", name="ck_tickets_source"),
        sa.CheckConstraint("csat BETWEEN 1 AND 5", name="ck_tickets_csat"),
        sa.ForeignKeyConstraint(["user_id"], ["retail.customers.user_id"], name="fk_tickets_user_id_customers"),
        sa.ForeignKeyConstraint(["order_id"], ["retail.orders.order_id"], name="fk_tickets_order_id_orders"),
        sa.ForeignKeyConstraint(["product_id"], ["retail.products.product_id"], name="fk_tickets_product_id_products"),
        sa.PrimaryKeyConstraint("ticket_id", name="pk_tickets"),
        schema="support",
    )
    for column in ("user_id", "product_id", "created_at", "status"):
        op.create_index(f"ix_tickets_{column}", "tickets", [column], schema="support")

    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("embedding", EMBEDDING, nullable=True),
        sa.CheckConstraint("author IN ('customer', 'agent', 'system')", name="ck_ticket_messages_author"),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["support.tickets.ticket_id"], name="fk_ticket_messages_ticket_id_tickets"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ticket_messages"),
        sa.UniqueConstraint("ticket_id", "position", name="uq_ticket_messages_ticket_id_position"),
        schema="support",
    )
    op.create_index("ix_ticket_messages_created_at", "ticket_messages", ["created_at"], schema="support")
    _hnsw("ticket_messages", "support")

    op.create_table(
        "daily",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Double(), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.CheckConstraint("dimension IN ('store', 'category', 'carrier', 'region')", name="ck_daily_dimension"),
        sa.PrimaryKeyConstraint("day", "metric", "dimension", "key", name="pk_daily"),
        schema="kpi",
    )
    op.create_index("ix_daily_metric_dimension_key_day", "daily", ["metric", "dimension", "key", "day"], schema="kpi")


def downgrade() -> None:
    op.drop_table("daily", schema="kpi")
    op.drop_table("ticket_messages", schema="support")
    op.drop_table("tickets", schema="support")
    op.drop_table("reviews", schema="retail")
    op.drop_table("refunds", schema="retail")
    op.drop_table("shipments", schema="retail")
    op.drop_column("orders", "placed_at", schema="retail")
    op.execute("DROP SCHEMA IF EXISTS kpi")
    op.execute("DROP SCHEMA IF EXISTS support")
