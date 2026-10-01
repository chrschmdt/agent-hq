from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from ahq.domain import DuplicateCall
from ahq.domain.retail import Order, Product, RetailChange, RetailSnapshot, User, Variant
from ahq.domain.tools import ToolCallRecord


class InMemoryRetailRepo:
    def __init__(self, snapshot: RetailSnapshot) -> None:
        self._snapshot = snapshot
        self._calls: dict[str, ToolCallRecord] = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[_MemorySession]:
        async with self._lock:
            session = _MemorySession(self._snapshot, set(self._calls))
            yield session
            self._snapshot = session.result()
            self._calls.update({call.key: call for call in session.calls})

    async def snapshot(self) -> RetailSnapshot:
        return self._snapshot

    async def load(self, snapshot: RetailSnapshot) -> None:
        async with self._lock:
            self._snapshot = snapshot

    async def recorded_call(self, key: str) -> ToolCallRecord | None:
        return self._calls.get(key)

    def clear_activity(self) -> dict[str, int]:
        count = len(self._calls)
        self._calls = {}
        return {"agents.tool_calls_audit": count}


class _MemorySession:
    def __init__(self, snapshot: RetailSnapshot, recorded: set[str]) -> None:
        self._base = snapshot
        self._users = dict(snapshot.users)
        self._orders = dict(snapshot.orders)
        self._recorded = recorded
        self.calls: list[ToolCallRecord] = []

    async def user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    async def user_id_by_email(self, email: str) -> str | None:
        wanted = email.lower()
        return next((user.user_id for user in self._users.values() if user.email.lower() == wanted), None)

    async def user_id_by_name_zip(self, first_name: str, last_name: str, zip: str) -> str | None:
        return next(
            (
                user.user_id
                for user in self._users.values()
                if user.name.first_name.lower() == first_name.lower()
                and user.name.last_name.lower() == last_name.lower()
                and user.address.zip == zip
            ),
            None,
        )

    async def order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    async def product(self, product_id: str) -> Product | None:
        return self._base.products.get(product_id)

    async def variant(self, item_id: str) -> Variant | None:
        for product in self._base.products.values():
            if item_id in product.variants:
                return product.variants[item_id]
        return None

    async def products(self) -> list[Product]:
        return list(self._base.products.values())

    async def save(self, change: RetailChange) -> None:
        if change.call is not None:
            if change.call.key in self._recorded:
                raise DuplicateCall(change.call.key)
            self._recorded.add(change.call.key)
            self.calls.append(change.call)
        for user in change.users:
            self._users[user.user_id] = user
        for order in change.orders:
            self._orders[order.order_id] = order

    def result(self) -> RetailSnapshot:
        return self._base.model_copy(update={"users": self._users, "orders": self._orders})
