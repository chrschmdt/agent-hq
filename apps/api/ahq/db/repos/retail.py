from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncGenerator, Iterable, Sequence
from contextlib import asynccontextmanager
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ahq.db.models import (
    CustomerRow,
    OrderFulfillmentRow,
    OrderItemRow,
    OrderPaymentRow,
    OrderRow,
    PaymentMethodRow,
    ProductRow,
    ProductVariantRow,
    ToolCallAuditRow,
)
from ahq.domain import DuplicateCall, ToolCallRecord
from ahq.domain.retail import (
    Address,
    Fulfillment,
    Order,
    OrderItem,
    Payment,
    PaymentMethod,
    Product,
    RetailChange,
    RetailSnapshot,
    User,
    UserName,
    Variant,
)

_PAYMENT_METHOD: TypeAdapter[PaymentMethod] = TypeAdapter(PaymentMethod)
_ADDRESS_FIELDS = ("address1", "address2", "city", "country", "state", "zip")
_TABLES = (
    OrderFulfillmentRow,
    OrderPaymentRow,
    OrderItemRow,
    OrderRow,
    ProductVariantRow,
    ProductRow,
    PaymentMethodRow,
    CustomerRow,
)


class PgRetailRepo:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[PgRetailSession]:
        async with self._sessions.begin() as session:
            yield PgRetailSession(session)

    async def snapshot(self) -> RetailSnapshot:
        async with self._sessions() as session:
            products = _assemble_products(
                await _all(session, ProductRow, ProductRow.position),
                await _all(session, ProductVariantRow, ProductVariantRow.product_id, ProductVariantRow.position),
            )
            orders = await _assemble_orders(session, await _all(session, OrderRow, OrderRow.position))
            users = _assemble_users(
                await _all(session, CustomerRow, CustomerRow.position),
                await _all(session, PaymentMethodRow, PaymentMethodRow.user_id, PaymentMethodRow.position),
                orders.values(),
            )
        return RetailSnapshot(products=products, users=users, orders=orders)

    async def load(self, snapshot: RetailSnapshot) -> None:
        async with self._sessions.begin() as session:
            await session.execute(text(f"TRUNCATE {', '.join(_qualified(table) for table in _TABLES)} CASCADE"))
            await _insert(session, CustomerRow, [_customer_row(u, i) for i, u in enumerate(snapshot.users.values())])
            await _insert(
                session,
                PaymentMethodRow,
                [
                    _payment_method_row(u.user_id, m, i)
                    for u in snapshot.users.values()
                    for i, m in enumerate(u.payment_methods.values())
                ],
            )
            await _insert(
                session,
                ProductRow,
                [
                    {"product_id": p.product_id, "position": i, "name": p.name}
                    for i, p in enumerate(snapshot.products.values())
                ],
            )
            await _insert(
                session,
                ProductVariantRow,
                [
                    _variant_row(p.product_id, v, i)
                    for p in snapshot.products.values()
                    for i, v in enumerate(p.variants.values())
                ],
            )
            await _insert(session, OrderRow, [_order_row(o, i) for i, o in enumerate(snapshot.orders.values())])
            await _insert_order_children(session, snapshot.orders.values())

    async def recorded_call(self, key: str) -> ToolCallRecord | None:
        async with self._sessions() as session:
            row = await session.get(ToolCallAuditRow, key)
        if row is None:
            return None
        return ToolCallRecord(
            key=row.key,
            work_item_id=row.work_item_id,
            subject=row.subject,
            tool=row.tool,
            arguments=row.arguments,
            output=row.output,
            approval_id=row.approval_id,
            recorded_at=row.recorded_at,
        )


class PgRetailSession:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def user(self, user_id: str) -> User | None:
        row = await self._session.scalar(
            select(CustomerRow).where(CustomerRow.user_id == user_id).with_for_update(key_share=True)
        )
        if row is None:
            return None
        methods = await self._session.scalars(
            select(PaymentMethodRow).where(PaymentMethodRow.user_id == user_id).order_by(PaymentMethodRow.position)
        )
        order_ids = await self._session.scalars(
            select(OrderRow.order_id).where(OrderRow.user_id == user_id).order_by(OrderRow.position)
        )
        return _to_user(row, methods, list(order_ids))

    async def user_id_by_email(self, email: str) -> str | None:
        query = select(CustomerRow.user_id).where(func.lower(CustomerRow.email) == email.lower())
        return await self._session.scalar(query.order_by(CustomerRow.position).limit(1))

    async def user_id_by_name_zip(self, first_name: str, last_name: str, zip: str) -> str | None:
        query = select(CustomerRow.user_id).where(
            func.lower(CustomerRow.first_name) == first_name.lower(),
            func.lower(CustomerRow.last_name) == last_name.lower(),
            CustomerRow.zip == zip,
        )
        return await self._session.scalar(query.order_by(CustomerRow.position).limit(1))

    async def order(self, order_id: str) -> Order | None:
        row = await self._session.scalar(
            select(OrderRow).where(OrderRow.order_id == order_id).with_for_update(key_share=True)
        )
        if row is None:
            return None
        return (await _assemble_orders(self._session, [row]))[order_id]

    async def product(self, product_id: str) -> Product | None:
        row = await self._session.scalar(select(ProductRow).where(ProductRow.product_id == product_id))
        if row is None:
            return None
        variants = await self._session.scalars(
            select(ProductVariantRow)
            .where(ProductVariantRow.product_id == product_id)
            .order_by(ProductVariantRow.position)
        )
        return _assemble_products([row], variants)[product_id]

    async def variant(self, item_id: str) -> Variant | None:
        row = await self._session.scalar(select(ProductVariantRow).where(ProductVariantRow.item_id == item_id))
        return None if row is None else _to_variant(row)

    async def products(self) -> list[Product]:
        products = _assemble_products(
            await _all(self._session, ProductRow, ProductRow.position),
            await _all(self._session, ProductVariantRow, ProductVariantRow.product_id, ProductVariantRow.position),
        )
        return list(products.values())

    async def save(self, change: RetailChange) -> None:
        if change.call is not None:
            recorded = await self._session.scalar(
                pg_insert(ToolCallAuditRow)
                .values(change.call.model_dump())
                .on_conflict_do_nothing(index_elements=[ToolCallAuditRow.key])
                .returning(ToolCallAuditRow.key)
            )
            if recorded is None:
                raise DuplicateCall(change.call.key)
        for user in change.users:
            await self._session.execute(
                update(CustomerRow)
                .where(CustomerRow.user_id == user.user_id)
                .values(
                    first_name=user.name.first_name,
                    last_name=user.name.last_name,
                    email=user.email,
                    **user.address.model_dump(),
                )
            )
            for position, method in enumerate(user.payment_methods.values()):
                values = _payment_method_row(user.user_id, method, position)
                await self._session.execute(
                    update(PaymentMethodRow).where(PaymentMethodRow.id == method.id).values(values)
                )
        for order in change.orders:
            await self._session.execute(
                update(OrderRow).where(OrderRow.order_id == order.order_id).values(_order_values(order))
            )
            for table in (OrderItemRow, OrderPaymentRow, OrderFulfillmentRow):
                await self._session.execute(delete(table).where(table.order_id == order.order_id))
        await _insert_order_children(self._session, change.orders)


async def _all(session: AsyncSession, model: type[Any], *order_by: Any) -> list[Any]:
    return list(await session.scalars(select(model).order_by(*order_by)))


async def _insert(session: AsyncSession, model: type[Any], rows: list[dict[str, Any]]) -> None:
    if rows:
        await session.execute(insert(model), rows)


async def _insert_order_children(session: AsyncSession, orders: Iterable[Order]) -> None:
    orders = list(orders)
    await _insert(
        session,
        OrderItemRow,
        [
            {"order_id": o.order_id, "position": i, **item.model_dump()}
            for o in orders
            for i, item in enumerate(o.items)
        ],
    )
    await _insert(
        session,
        OrderPaymentRow,
        [
            {"order_id": o.order_id, "position": i, **p.model_dump()}
            for o in orders
            for i, p in enumerate(o.payment_history)
        ],
    )
    await _insert(
        session,
        OrderFulfillmentRow,
        [
            {"order_id": o.order_id, "position": i, "tracking_ids": f.tracking_id, "item_ids": f.item_ids}
            for o in orders
            for i, f in enumerate(o.fulfillments)
        ],
    )


async def _assemble_orders(session: AsyncSession, rows: Sequence[OrderRow]) -> dict[str, Order]:
    order_ids = [row.order_id for row in rows]
    items = await _children(session, OrderItemRow, order_ids)
    payments = await _children(session, OrderPaymentRow, order_ids)
    fulfillments = await _children(session, OrderFulfillmentRow, order_ids)
    return {
        row.order_id: _to_order(row, items[row.order_id], payments[row.order_id], fulfillments[row.order_id])
        for row in rows
    }


async def _children(session: AsyncSession, model: type[Any], order_ids: list[str]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    query = select(model).where(model.order_id.in_(order_ids)).order_by(model.order_id, model.position)
    for row in await session.scalars(query):
        grouped[row.order_id].append(row)
    return grouped


def _assemble_products(rows: Iterable[ProductRow], variants: Iterable[ProductVariantRow]) -> dict[str, Product]:
    by_product: dict[str, dict[str, Variant]] = defaultdict(dict)
    for variant in variants:
        by_product[variant.product_id][variant.item_id] = _to_variant(variant)
    return {
        row.product_id: Product(name=row.name, product_id=row.product_id, variants=by_product[row.product_id])
        for row in rows
    }


def _assemble_users(
    rows: Iterable[CustomerRow], methods: Iterable[PaymentMethodRow], orders: Iterable[Order]
) -> dict[str, User]:
    methods_by_user: dict[str, list[PaymentMethodRow]] = defaultdict(list)
    for method in methods:
        methods_by_user[method.user_id].append(method)
    orders_by_user: dict[str, list[str]] = defaultdict(list)
    for order in orders:
        orders_by_user[order.user_id].append(order.order_id)
    return {row.user_id: _to_user(row, methods_by_user[row.user_id], orders_by_user[row.user_id]) for row in rows}


def _to_user(row: CustomerRow, methods: Iterable[PaymentMethodRow], order_ids: list[str]) -> User:
    return User(
        user_id=row.user_id,
        name=UserName(first_name=row.first_name, last_name=row.last_name),
        address=_address(row),
        email=row.email,
        payment_methods={method.id: _to_payment_method(method) for method in methods},
        orders=order_ids,
    )


def _to_payment_method(row: PaymentMethodRow) -> PaymentMethod:
    fields: dict[str, Any] = {"source": row.source, "id": row.id}
    if row.source == "credit_card":
        fields |= {"brand": row.brand, "last_four": row.last_four}
    elif row.source == "gift_card":
        fields["balance"] = row.balance
    return _PAYMENT_METHOD.validate_python(fields)


def _to_variant(row: ProductVariantRow) -> Variant:
    return Variant(item_id=row.item_id, options=row.options, available=row.available, price=row.price)


def _to_order(
    row: OrderRow,
    items: Iterable[OrderItemRow],
    payments: Iterable[OrderPaymentRow],
    fulfillments: Iterable[OrderFulfillmentRow],
) -> Order:
    return Order.model_validate(
        {
            "order_id": row.order_id,
            "user_id": row.user_id,
            "address": _address(row),
            "items": [
                OrderItem(name=i.name, product_id=i.product_id, item_id=i.item_id, price=i.price, options=i.options)
                for i in items
            ],
            "status": row.status,
            "fulfillments": [Fulfillment(tracking_id=f.tracking_ids, item_ids=f.item_ids) for f in fulfillments],
            "payment_history": [
                Payment.model_validate(
                    {
                        "transaction_type": p.transaction_type,
                        "amount": p.amount,
                        "payment_method_id": p.payment_method_id,
                    }
                )
                for p in payments
            ],
            "cancel_reason": row.cancel_reason,
            "exchange_items": row.exchange_items,
            "exchange_new_items": row.exchange_new_items,
            "exchange_payment_method_id": row.exchange_payment_method_id,
            "exchange_price_difference": row.exchange_price_difference,
            "return_items": row.return_items,
            "return_payment_method_id": row.return_payment_method_id,
        }
    )


def _address(row: CustomerRow | OrderRow) -> Address:
    return Address(**{field: getattr(row, field) for field in _ADDRESS_FIELDS})


def _customer_row(user: User, position: int) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "position": position,
        "first_name": user.name.first_name,
        "last_name": user.name.last_name,
        "email": user.email,
        **user.address.model_dump(),
    }


def _payment_method_row(user_id: str, method: PaymentMethod, position: int) -> dict[str, Any]:
    fields = method.model_dump()
    return {
        "id": method.id,
        "user_id": user_id,
        "position": position,
        "source": method.source,
        "brand": fields.get("brand"),
        "last_four": fields.get("last_four"),
        "balance": fields.get("balance"),
    }


def _variant_row(product_id: str, variant: Variant, position: int) -> dict[str, Any]:
    return {"product_id": product_id, "position": position, **variant.model_dump()}


def _order_row(order: Order, position: int) -> dict[str, Any]:
    return {"order_id": order.order_id, "position": position, **_order_values(order)}


def _order_values(order: Order) -> dict[str, Any]:
    return {
        "user_id": order.user_id,
        "status": order.status,
        **order.address.model_dump(),
        "cancel_reason": order.cancel_reason,
        "exchange_items": order.exchange_items,
        "exchange_new_items": order.exchange_new_items,
        "exchange_payment_method_id": order.exchange_payment_method_id,
        "exchange_price_difference": order.exchange_price_difference,
        "return_items": order.return_items,
        "return_payment_method_id": order.return_payment_method_id,
    }


def _qualified(model: type[Any]) -> str:
    table = model.__table__
    return f"{table.schema}.{table.name}"
