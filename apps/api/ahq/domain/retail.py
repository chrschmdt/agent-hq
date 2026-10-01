from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ahq.domain.base import StrictModel
from ahq.domain.tools import ToolCallRecord

OrderStatus = Literal[
    "processed",
    "pending",
    "pending (item modified)",
    "delivered",
    "cancelled",
    "exchange requested",
    "return requested",
]
CancelReason = Literal["no longer needed", "ordered by mistake"]
TransactionType = Literal["payment", "refund"]


class Address(StrictModel):
    address1: str
    address2: str
    city: str
    country: str
    state: str
    zip: str


class UserName(StrictModel):
    first_name: str
    last_name: str


class CreditCard(StrictModel):
    source: Literal["credit_card"]
    id: str
    brand: str
    last_four: str


class Paypal(StrictModel):
    source: Literal["paypal"]
    id: str


class GiftCard(StrictModel):
    source: Literal["gift_card"]
    id: str
    balance: float


PaymentMethod = Annotated[CreditCard | GiftCard | Paypal, Field(discriminator="source")]


class User(StrictModel):
    user_id: str
    name: UserName
    address: Address
    email: str
    payment_methods: dict[str, PaymentMethod]
    orders: list[str]


class Variant(StrictModel):
    item_id: str
    options: dict[str, str]
    available: bool
    price: float


class Product(StrictModel):
    name: str
    product_id: str
    variants: dict[str, Variant]


class OrderItem(StrictModel):
    name: str
    product_id: str
    item_id: str
    price: float
    options: dict[str, str]


class Fulfillment(StrictModel):
    tracking_id: list[str]
    item_ids: list[str]


class Payment(StrictModel):
    transaction_type: TransactionType
    amount: float
    payment_method_id: str


class Order(StrictModel):
    order_id: str
    user_id: str
    address: Address
    items: list[OrderItem]
    status: OrderStatus
    fulfillments: list[Fulfillment]
    payment_history: list[Payment]
    cancel_reason: CancelReason | None = None
    exchange_items: list[str] | None = None
    exchange_new_items: list[str] | None = None
    exchange_payment_method_id: str | None = None
    exchange_price_difference: float | None = None
    return_items: list[str] | None = None
    return_payment_method_id: str | None = None


class RetailSnapshot(StrictModel):
    products: dict[str, Product]
    users: dict[str, User]
    orders: dict[str, Order]


class RetailChange(StrictModel):
    users: tuple[User, ...] = ()
    orders: tuple[Order, ...] = ()
    call: ToolCallRecord | None = None
