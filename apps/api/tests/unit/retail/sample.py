from __future__ import annotations

from ahq.domain.retail import (
    Address,
    CreditCard,
    GiftCard,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    Product,
    RetailSnapshot,
    User,
    UserName,
    Variant,
)

HOME = Address(address1="1 Main St", address2="", city="Austin", country="USA", state="TX", zip="78701")
CARD = "credit_card_1"
GIFT = "gift_card_1"

MUG = Product(
    name="Mug",
    product_id="p_mug",
    variants={
        "mug_small": Variant(item_id="mug_small", options={"size": "small"}, available=True, price=10.0),
        "mug_large": Variant(item_id="mug_large", options={"size": "large"}, available=True, price=12.5),
        "mug_gold": Variant(item_id="mug_gold", options={"size": "gold"}, available=False, price=90.0),
    },
)
LAMP = Product(
    name="Lamp",
    product_id="p_lamp",
    variants={
        "lamp_white": Variant(item_id="lamp_white", options={"color": "white"}, available=True, price=40.0),
        "lamp_black": Variant(item_id="lamp_black", options={"color": "black"}, available=True, price=55.0),
    },
)


def item(product: Product, item_id: str) -> OrderItem:
    variant = product.variants[item_id]
    return OrderItem(
        name=product.name, product_id=product.product_id, item_id=item_id, price=variant.price, options=variant.options
    )


def order(order_id: str, status: OrderStatus, *, paid_with: str = CARD) -> Order:
    items = [item(MUG, "mug_small"), item(LAMP, "lamp_white")]
    return Order(
        order_id=order_id,
        user_id="ada_1",
        address=HOME,
        items=items,
        status=status,
        fulfillments=[],
        payment_history=[
            Payment(transaction_type="payment", amount=sum(i.price for i in items), payment_method_id=paid_with)
        ],
    )


ORDERS = [
    order("#pending", "pending"),
    order("#pending_gift", "pending", paid_with=GIFT),
    order("#modified", "pending (item modified)"),
    order("#processed", "processed"),
    order("#delivered", "delivered"),
]

ADA = User(
    user_id="ada_1",
    name=UserName(first_name="Ada", last_name="Lovelace"),
    address=HOME,
    email="Ada@Example.com",
    payment_methods={
        CARD: CreditCard(source="credit_card", id=CARD, brand="visa", last_four="4242"),
        GIFT: GiftCard(source="gift_card", id=GIFT, balance=100.0),
    },
    orders=[o.order_id for o in ORDERS],
)


def sample_store() -> RetailSnapshot:
    return RetailSnapshot(
        products={MUG.product_id: MUG, LAMP.product_id: LAMP},
        users={ADA.user_id: ADA},
        orders={o.order_id: o for o in ORDERS},
    )
