from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SCHEMA = "retail"
TEXT_ARRAY = postgresql.ARRAY(sa.Text())


def _address() -> list[sa.Column[str]]:
    return [
        sa.Column(name, sa.Text(), nullable=False)
        for name in ("address1", "address2", "city", "country", "state", "zip")
    ]


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "customers",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        *_address(),
        sa.PrimaryKeyConstraint("user_id", name="pk_customers"),
        schema=SCHEMA,
    )
    op.create_index("uq_customers_lower_email", "customers", [sa.text("lower(email)")], unique=True, schema=SCHEMA)
    op.create_index(
        "ix_customers_lower_name_zip",
        "customers",
        [sa.text("lower(first_name)"), sa.text("lower(last_name)"), "zip"],
        schema=SCHEMA,
    )

    op.create_table(
        "payment_methods",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("last_four", sa.Text(), nullable=True),
        sa.Column("balance", sa.Double(), nullable=True),
        sa.CheckConstraint("source IN ('credit_card', 'gift_card', 'paypal')", name="ck_payment_methods_source"),
        sa.ForeignKeyConstraint(["user_id"], ["retail.customers.user_id"], name="fk_payment_methods_user_id_customers"),
        sa.PrimaryKeyConstraint("id", name="pk_payment_methods"),
        schema=SCHEMA,
    )
    op.create_index("ix_payment_methods_user_id_position", "payment_methods", ["user_id", "position"], schema=SCHEMA)

    op.create_table(
        "products",
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("product_id", name="pk_products"),
        sa.UniqueConstraint("name", name="uq_products_name"),
        schema=SCHEMA,
    )

    op.create_table(
        "product_variants",
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("price", sa.Double(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"], ["retail.products.product_id"], name="fk_product_variants_product_id_products"
        ),
        sa.PrimaryKeyConstraint("item_id", name="pk_product_variants"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_product_variants_product_id_position", "product_variants", ["product_id", "position"], schema=SCHEMA
    )

    op.create_table(
        "orders",
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        *_address(),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("exchange_items", TEXT_ARRAY, nullable=True),
        sa.Column("exchange_new_items", TEXT_ARRAY, nullable=True),
        sa.Column("exchange_payment_method_id", sa.Text(), nullable=True),
        sa.Column("exchange_price_difference", sa.Double(), nullable=True),
        sa.Column("return_items", TEXT_ARRAY, nullable=True),
        sa.Column("return_payment_method_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["retail.customers.user_id"], name="fk_orders_user_id_customers"),
        sa.PrimaryKeyConstraint("order_id", name="pk_orders"),
        schema=SCHEMA,
    )
    op.create_index("ix_orders_user_id_position", "orders", ["user_id", "position"], schema=SCHEMA)
    op.create_index("ix_orders_status", "orders", ["status"], schema=SCHEMA)

    op.create_table(
        "order_items",
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("price", sa.Double(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["retail.orders.order_id"], name="fk_order_items_order_id_orders"),
        sa.ForeignKeyConstraint(
            ["product_id"], ["retail.products.product_id"], name="fk_order_items_product_id_products"
        ),
        sa.ForeignKeyConstraint(
            ["item_id"], ["retail.product_variants.item_id"], name="fk_order_items_item_id_product_variants"
        ),
        sa.PrimaryKeyConstraint("order_id", "position", name="pk_order_items"),
        schema=SCHEMA,
    )
    op.create_index("ix_order_items_item_id", "order_items", ["item_id"], schema=SCHEMA)
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"], schema=SCHEMA)

    op.create_table(
        "order_payments",
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("transaction_type", sa.Text(), nullable=False),
        sa.Column("amount", sa.Double(), nullable=False),
        sa.Column("payment_method_id", sa.Text(), nullable=False),
        sa.CheckConstraint("transaction_type IN ('payment', 'refund')", name="ck_order_payments_transaction_type"),
        sa.ForeignKeyConstraint(["order_id"], ["retail.orders.order_id"], name="fk_order_payments_order_id_orders"),
        sa.ForeignKeyConstraint(
            ["payment_method_id"],
            ["retail.payment_methods.id"],
            name="fk_order_payments_payment_method_id_payment_methods",
        ),
        sa.PrimaryKeyConstraint("order_id", "position", name="pk_order_payments"),
        schema=SCHEMA,
    )

    op.create_table(
        "order_fulfillments",
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("tracking_ids", TEXT_ARRAY, nullable=False),
        sa.Column("item_ids", TEXT_ARRAY, nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["retail.orders.order_id"], name="fk_order_fulfillments_order_id_orders"),
        sa.PrimaryKeyConstraint("order_id", "position", name="pk_order_fulfillments"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    for table in (
        "order_fulfillments",
        "order_payments",
        "order_items",
        "orders",
        "product_variants",
        "products",
        "payment_methods",
        "customers",
    ):
        op.drop_table(table, schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA}")
