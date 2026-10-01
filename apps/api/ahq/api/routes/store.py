from __future__ import annotations

from fastapi import APIRouter

from ahq.api.deps import ContainerDep, Operator
from ahq.domain import NotFoundError, StrictModel
from ahq.domain.retail import Order, User
from ahq.domain.world import Shipment

router = APIRouter(tags=["store"])


class OrderView(StrictModel):
    order: Order
    shipments: list[Shipment]


@router.get("/api/store/orders/{order_id}")
async def get_order(order_id: str, container: ContainerDep, _: Operator) -> OrderView:
    async with container.retail.session() as store:
        order = await store.order(order_id)
    if order is None:
        raise NotFoundError(f"order {order_id} not found")
    shipments = [shipment for shipment in await container.world.shipments() if shipment.order_id == order_id]
    return OrderView(order=order, shipments=shipments)


@router.get("/api/store/customers/{user_id}")
async def get_customer(user_id: str, container: ContainerDep, _: Operator) -> User:
    async with container.retail.session() as store:
        user = await store.user(user_id)
    if user is None:
        raise NotFoundError(f"customer {user_id} not found")
    return user
