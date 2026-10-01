from __future__ import annotations

import ast
import json
from collections.abc import Callable, Iterable, Mapping, Sequence

from ahq.domain.retail import (
    Address,
    CancelReason,
    GiftCard,
    Order,
    OrderItem,
    Payment,
    PaymentMethod,
    Product,
    User,
    Variant,
)
from ahq.retail.types import RetailError

CANCEL_REASONS: frozenset[CancelReason] = frozenset({"no longer needed", "ordered by mistake"})
TRANSFER_MESSAGE = "Transfer successful"

_CALCULATOR_CHARACTERS = frozenset("0123456789+-*/(). ")
_BINARY: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Pow: lambda a, b: a**b,
}
_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {ast.UAdd: lambda a: +a, ast.USub: lambda a: -a}
_MAX_EXPONENT = 1000


def calculate(expression: str) -> str:
    if not all(char in _CALCULATOR_CHARACTERS for char in expression):
        raise RetailError("Invalid characters in expression")
    try:
        tree = ast.parse(expression, filename="<string>", mode="eval")
        value = _evaluate(tree.body)
    except (SyntaxError, ArithmeticError) as error:
        raise RetailError(str(error)) from error
    return str(round(float(value), 2))


def _evaluate(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise OverflowError("exponent too large")
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    raise SyntaxError("invalid syntax")


def list_all_product_types(products: Iterable[Product]) -> str:
    return json.dumps({product.name: product.product_id for product in products}, sort_keys=True)


def cancel_pending_order(order: Order, user: User, reason: str) -> tuple[Order, User]:
    if order.status != "pending":
        raise RetailError("Non-pending order cannot be cancelled")
    if reason not in CANCEL_REASONS:
        raise RetailError("Invalid reason")
    methods = dict(user.payment_methods)
    refunds: list[Payment] = []
    for payment in order.payment_history:
        refunds.append(
            Payment(transaction_type="refund", amount=payment.amount, payment_method_id=payment.payment_method_id)
        )
        method = _payment_method(methods, payment.payment_method_id)
        if isinstance(method, GiftCard):
            methods[method.id] = _with_balance(method, method.balance + payment.amount)
    cancelled = order.model_copy(
        update={"status": "cancelled", "cancel_reason": reason, "payment_history": [*order.payment_history, *refunds]}
    )
    return cancelled, user.model_copy(update={"payment_methods": methods})


def issue_refund(order: Order, user: User, amount: float) -> tuple[Order, User]:
    if _is_pending(order) or order.status == "cancelled":
        raise RetailError("Only a processed or delivered order can get a goodwill refund")
    if amount <= 0:
        raise RetailError("Refund amount must be positive")
    paid = sum(p.amount for p in order.payment_history if p.transaction_type == "payment")
    refunded = sum(p.amount for p in order.payment_history if p.transaction_type == "refund")
    left = round(paid - refunded, 2)
    if round(amount, 2) > left:
        raise RetailError(f"Refund exceeds the {left:.2f} left to refund on this order")
    original = order.payment_history[0].payment_method_id
    methods = dict(user.payment_methods)
    method = _payment_method(methods, original)
    if isinstance(method, GiftCard):
        methods[method.id] = _with_balance(method, method.balance + round(amount, 2))
    refund = Payment(transaction_type="refund", amount=round(amount, 2), payment_method_id=original)
    refunded_order = order.model_copy(update={"payment_history": [*order.payment_history, refund]})
    return refunded_order, user.model_copy(update={"payment_methods": methods})


def exchange_delivered_order_items(
    order: Order,
    user: User,
    products: Mapping[str, Product],
    item_ids: Sequence[str],
    new_item_ids: Sequence[str],
    payment_method_id: str,
) -> Order:
    if order.status != "delivered":
        raise RetailError("Non-delivered order cannot be exchanged")
    _require_items(order, item_ids, lambda item_id: f"Number of {item_id} not found.")
    if len(item_ids) != len(new_item_ids):
        raise RetailError("The number of items to be exchanged should match.")
    diff_price: float = 0
    for item_id, new_item_id in zip(item_ids, new_item_ids, strict=True):
        item = _first_item(order.items, item_id)
        variant = _available_variant(products, item.product_id, new_item_id)
        diff_price += variant.price - item.price
    diff_price = round(diff_price, 2)
    method = _payment_method(user.payment_methods, payment_method_id)
    if isinstance(method, GiftCard) and method.balance < diff_price:
        raise RetailError("Insufficient gift card balance to pay for the price difference")
    return order.model_copy(
        update={
            "status": "exchange requested",
            "exchange_items": sorted(item_ids),
            "exchange_new_items": sorted(new_item_ids),
            "exchange_payment_method_id": payment_method_id,
            "exchange_price_difference": diff_price,
        }
    )


def modify_pending_order_address(order: Order, address: Address) -> Order:
    if not _is_pending(order):
        raise RetailError("Non-pending order cannot be modified")
    return order.model_copy(update={"address": address})


def modify_pending_order_items(
    order: Order,
    user: User,
    products: Mapping[str, Product],
    item_ids: Sequence[str],
    new_item_ids: Sequence[str],
    payment_method_id: str,
) -> tuple[Order, User]:
    if order.status != "pending":
        raise RetailError("Non-pending order cannot be modified")
    _require_items(order, item_ids, lambda item_id: f"{item_id} not found")
    if len(item_ids) != len(new_item_ids):
        raise RetailError("The number of items to be exchanged should match")
    diff_price: float = 0
    new_variants: list[Variant] = []
    for item_id, new_item_id in zip(item_ids, new_item_ids, strict=True):
        if item_id == new_item_id:
            raise RetailError("The new item id should be different from the old item id")
        item = _first_item(order.items, item_id)
        variant = _available_variant(products, item.product_id, new_item_id)
        new_variants.append(variant)
        diff_price += variant.price - item.price
    methods = dict(user.payment_methods)
    method = _payment_method(methods, payment_method_id)
    if isinstance(method, GiftCard) and method.balance < diff_price:
        raise RetailError("Insufficient gift card balance to pay for the new item")
    settlement = Payment(
        transaction_type="payment" if diff_price > 0 else "refund",
        amount=abs(diff_price),
        payment_method_id=payment_method_id,
    )
    if isinstance(method, GiftCard):
        methods[method.id] = _with_balance(method, method.balance - diff_price)
    items = list(order.items)
    for item_id, variant in zip(item_ids, new_variants, strict=True):
        index = next(index for index, item in enumerate(items) if item.item_id == item_id)
        items[index] = items[index].model_copy(
            update={"item_id": variant.item_id, "price": variant.price, "options": dict(variant.options)}
        )
    modified = order.model_copy(
        update={
            "items": items,
            "status": "pending (item modified)",
            "payment_history": [*order.payment_history, settlement],
        }
    )
    return modified, user.model_copy(update={"payment_methods": methods})


def modify_pending_order_payment(order: Order, user: User, payment_method_id: str) -> tuple[Order, User]:
    if not _is_pending(order):
        raise RetailError("Non-pending order cannot be modified")
    methods = dict(user.payment_methods)
    method = _payment_method(methods, payment_method_id)
    history = order.payment_history
    if len(history) != 1 or history[0].transaction_type != "payment":
        raise RetailError("There should be exactly one payment for a pending order")
    original = history[0]
    if original.payment_method_id == payment_method_id:
        raise RetailError("The new payment method should be different from the current one")
    amount = original.amount
    if isinstance(method, GiftCard) and method.balance < amount:
        raise RetailError("Insufficient gift card balance to pay for the order")
    moved = order.model_copy(
        update={
            "payment_history": [
                *history,
                Payment(transaction_type="payment", amount=amount, payment_method_id=payment_method_id),
                Payment(transaction_type="refund", amount=amount, payment_method_id=original.payment_method_id),
            ]
        }
    )
    if isinstance(method, GiftCard):
        methods[method.id] = _with_balance(method, method.balance - amount)
    old_method = _payment_method(methods, original.payment_method_id)
    if isinstance(old_method, GiftCard):
        methods[old_method.id] = _with_balance(old_method, old_method.balance + amount)
    return moved, user.model_copy(update={"payment_methods": methods})


def modify_user_address(user: User, address: Address) -> User:
    return user.model_copy(update={"address": address})


def return_delivered_order_items(order: Order, user: User, item_ids: Sequence[str], payment_method_id: str) -> Order:
    if order.status != "delivered":
        raise RetailError("Non-delivered order cannot be returned")
    method = _payment_method(user.payment_methods, payment_method_id)
    if not isinstance(method, GiftCard) and payment_method_id != order.payment_history[0].payment_method_id:
        raise RetailError("Payment method should be the original payment method")
    _require_items(order, item_ids, lambda _: "Some item not found")
    return order.model_copy(
        update={
            "status": "return requested",
            "return_items": sorted(item_ids),
            "return_payment_method_id": payment_method_id,
        }
    )


def _is_pending(order: Order) -> bool:
    return "pending" in order.status


def _require_items(order: Order, item_ids: Sequence[str], message: Callable[[str], str]) -> None:
    ordered = [item.item_id for item in order.items]
    for item_id in item_ids:
        if item_ids.count(item_id) > ordered.count(item_id):
            raise RetailError(message(item_id))


def _first_item(items: Sequence[OrderItem], item_id: str) -> OrderItem:
    item = next((item for item in items if item.item_id == item_id), None)
    if item is None:
        raise RetailError(f"Item {item_id} not found")
    return item


def _available_variant(products: Mapping[str, Product], product_id: str, item_id: str) -> Variant:
    product = products.get(product_id)
    if product is None:
        raise RetailError("Product not found")
    variant = product.variants.get(item_id)
    if variant is None:
        raise RetailError("Variant not found")
    if not variant.available:
        raise RetailError(f"New item {item_id} not found or available")
    return variant


def _payment_method(methods: Mapping[str, PaymentMethod], payment_method_id: str) -> PaymentMethod:
    method = methods.get(payment_method_id)
    if method is None:
        raise RetailError("Payment method not found")
    return method


def _with_balance(card: GiftCard, balance: float) -> GiftCard:
    return card.model_copy(update={"balance": round(balance, 2)})
