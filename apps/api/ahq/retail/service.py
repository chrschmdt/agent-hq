from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from ahq.domain.retail import Address, Order, Product, RetailChange, User, Variant
from ahq.domain.tools import ToolCallRecord
from ahq.ports import RetailRepo, RetailSession
from ahq.retail import operations
from ahq.retail.types import RetailError, format_output


class RetailService:
    def __init__(self, repo: RetailRepo, *, record: ToolCallRecord | None = None) -> None:
        self._repo = repo
        self._record = record

    def recording(self, record: ToolCallRecord) -> RetailService:
        return RetailService(self._repo, record=record)

    def _change(self, result: BaseModel, *, users: Sequence[User] = (), orders: Sequence[Order] = ()) -> RetailChange:
        record = None if self._record is None else self._record.model_copy(update={"output": format_output(result)})
        return RetailChange(users=tuple(users), orders=tuple(orders), call=record)

    async def calculate(self, expression: str) -> str:
        return operations.calculate(expression)

    async def transfer_to_human_agents(self, summary: str) -> str:
        return operations.TRANSFER_MESSAGE

    async def find_user_id_by_email(self, email: str) -> str:
        async with self._repo.session() as session:
            user_id = await session.user_id_by_email(email)
        if user_id is None:
            raise RetailError("User not found")
        return user_id

    async def find_user_id_by_name_zip(self, first_name: str, last_name: str, zip: str) -> str:
        async with self._repo.session() as session:
            user_id = await session.user_id_by_name_zip(first_name, last_name, zip)
        if user_id is None:
            raise RetailError("User not found")
        return user_id

    async def get_user_details(self, user_id: str) -> User:
        async with self._repo.session() as session:
            return await _user(session, user_id)

    async def get_order_details(self, order_id: str) -> Order:
        async with self._repo.session() as session:
            return await _order(session, order_id)

    async def get_product_details(self, product_id: str) -> Product:
        async with self._repo.session() as session:
            product = await session.product(product_id)
        if product is None:
            raise RetailError("Product not found")
        return product

    async def get_item_details(self, item_id: str) -> Variant:
        async with self._repo.session() as session:
            variant = await session.variant(item_id)
        if variant is None:
            raise RetailError("Item not found")
        return variant

    async def list_all_product_types(self) -> str:
        async with self._repo.session() as session:
            return operations.list_all_product_types(await session.products())

    async def cancel_pending_order(self, order_id: str, reason: str) -> Order:
        async with self._repo.session() as session:
            order = await _order(session, order_id)
            order, user = operations.cancel_pending_order(order, await _user(session, order.user_id), reason)
            await session.save(self._change(order, users=(user,), orders=(order,)))
        return order

    async def exchange_delivered_order_items(
        self, order_id: str, item_ids: Sequence[str], new_item_ids: Sequence[str], payment_method_id: str
    ) -> Order:
        async with self._repo.session() as session:
            order = await _order(session, order_id)
            order = operations.exchange_delivered_order_items(
                order,
                await _user(session, order.user_id),
                await _products_of(session, order),
                list(item_ids),
                list(new_item_ids),
                payment_method_id,
            )
            await session.save(self._change(order, orders=(order,)))
        return order

    async def modify_pending_order_address(
        self, order_id: str, address1: str, address2: str, city: str, state: str, country: str, zip: str
    ) -> Order:
        address = Address(address1=address1, address2=address2, city=city, country=country, state=state, zip=zip)
        async with self._repo.session() as session:
            order = operations.modify_pending_order_address(await _order(session, order_id), address)
            await session.save(self._change(order, orders=(order,)))
        return order

    async def modify_pending_order_items(
        self, order_id: str, item_ids: Sequence[str], new_item_ids: Sequence[str], payment_method_id: str
    ) -> Order:
        async with self._repo.session() as session:
            order = await _order(session, order_id)
            order, user = operations.modify_pending_order_items(
                order,
                await _user(session, order.user_id),
                await _products_of(session, order),
                list(item_ids),
                list(new_item_ids),
                payment_method_id,
            )
            await session.save(self._change(order, users=(user,), orders=(order,)))
        return order

    async def modify_pending_order_payment(self, order_id: str, payment_method_id: str) -> Order:
        async with self._repo.session() as session:
            order = await _order(session, order_id)
            order, user = operations.modify_pending_order_payment(
                order, await _user(session, order.user_id), payment_method_id
            )
            await session.save(self._change(order, users=(user,), orders=(order,)))
        return order

    async def modify_user_address(
        self, user_id: str, address1: str, address2: str, city: str, state: str, country: str, zip: str
    ) -> User:
        address = Address(address1=address1, address2=address2, city=city, country=country, state=state, zip=zip)
        async with self._repo.session() as session:
            user = operations.modify_user_address(await _user(session, user_id), address)
            await session.save(self._change(user, users=(user,)))
        return user

    async def issue_refund(self, order_id: str, amount: float, reason: str) -> Order:
        async with self._repo.session() as session:
            order = await _order(session, order_id)
            order, user = operations.issue_refund(order, await _user(session, order.user_id), amount)
            await session.save(self._change(order, users=(user,), orders=(order,)))
        return order

    async def return_delivered_order_items(
        self, order_id: str, item_ids: Sequence[str], payment_method_id: str
    ) -> Order:
        async with self._repo.session() as session:
            order = await _order(session, order_id)
            order = operations.return_delivered_order_items(
                order, await _user(session, order.user_id), list(item_ids), payment_method_id
            )
            await session.save(self._change(order, orders=(order,)))
        return order


async def _order(session: RetailSession, order_id: str) -> Order:
    order = await session.order(order_id)
    if order is None:
        raise RetailError("Order not found")
    return order


async def _user(session: RetailSession, user_id: str) -> User:
    user = await session.user(user_id)
    if user is None:
        raise RetailError("User not found")
    return user


async def _products_of(session: RetailSession, order: Order) -> dict[str, Product]:
    products: dict[str, Product] = {}
    for product_id in dict.fromkeys(item.product_id for item in order.items):
        product = await session.product(product_id)
        if product is not None:
            products[product_id] = product
    return products
