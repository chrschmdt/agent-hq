from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Double, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ahq.db.models.base import Base

SCHEMA = "retail"


class CustomerRow(Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index("uq_customers_lower_email", text("lower(email)"), unique=True),
        Index("ix_customers_lower_name_zip", text("lower(first_name)"), text("lower(last_name)"), "zip"),
        {"schema": SCHEMA},
    )

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    first_name: Mapped[str] = mapped_column(Text, nullable=False)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    address1: Mapped[str] = mapped_column(Text, nullable=False)
    address2: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    zip: Mapped[str] = mapped_column(Text, nullable=False)


class PaymentMethodRow(Base):
    __tablename__ = "payment_methods"
    __table_args__ = (
        CheckConstraint("source IN ('credit_card', 'gift_card', 'paypal')", name="source"),
        Index(None, "user_id", "position"),
        {"schema": SCHEMA},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("retail.customers.user_id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text)
    last_four: Mapped[str | None] = mapped_column(Text)
    balance: Mapped[float | None] = mapped_column(Double)


class ProductRow(Base):
    __tablename__ = "products"
    __table_args__ = ({"schema": SCHEMA},)

    product_id: Mapped[str] = mapped_column(Text, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class ProductVariantRow(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        Index(None, "product_id", "position"),
        {"schema": SCHEMA},
    )

    item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("retail.products.product_id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False)
    price: Mapped[float] = mapped_column(Double, nullable=False)


class OrderRow(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index(None, "user_id", "position"),
        Index(None, "status"),
        {"schema": SCHEMA},
    )

    order_id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("retail.customers.user_id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    address1: Mapped[str] = mapped_column(Text, nullable=False)
    address2: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    zip: Mapped[str] = mapped_column(Text, nullable=False)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    exchange_items: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    exchange_new_items: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    exchange_payment_method_id: Mapped[str | None] = mapped_column(Text)
    exchange_price_difference: Mapped[float | None] = mapped_column(Double)
    return_items: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    return_payment_method_id: Mapped[str | None] = mapped_column(Text)
    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderItemRow(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        Index(None, "item_id"),
        Index(None, "product_id"),
        {"schema": SCHEMA},
    )

    order_id: Mapped[str] = mapped_column(ForeignKey("retail.orders.order_id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    product_id: Mapped[str] = mapped_column(ForeignKey("retail.products.product_id"), nullable=False)
    item_id: Mapped[str] = mapped_column(ForeignKey("retail.product_variants.item_id"), nullable=False)
    price: Mapped[float] = mapped_column(Double, nullable=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class OrderPaymentRow(Base):
    __tablename__ = "order_payments"
    __table_args__ = (
        CheckConstraint("transaction_type IN ('payment', 'refund')", name="transaction_type"),
        {"schema": SCHEMA},
    )

    order_id: Mapped[str] = mapped_column(ForeignKey("retail.orders.order_id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_type: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float] = mapped_column(Double, nullable=False)
    payment_method_id: Mapped[str] = mapped_column(ForeignKey("retail.payment_methods.id"), nullable=False)


class OrderFulfillmentRow(Base):
    __tablename__ = "order_fulfillments"
    __table_args__ = ({"schema": SCHEMA},)

    order_id: Mapped[str] = mapped_column(ForeignKey("retail.orders.order_id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracking_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    item_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
