from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ahq.config import CarrierSpec, WorldConfig
from ahq.domain.retail import Order, RetailSnapshot
from ahq.domain.world import KpiDimension, KpiMetric, KpiPoint, Refund, Shipment, WorldHistory
from ahq.sim.seeded import rng

HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
LATE_DELAY_DAYS = (0.5, 3.0)

_WEEKLY_RHYTHM = (1.0, 0.96, 0.98, 1.0, 1.07, 1.16, 1.04)
_CATEGORY_REFUND_RATE = {
    "electronics": 0.09,
    "home": 0.07,
    "outdoors": 0.06,
    "apparel": 0.12,
    "personal_care": 0.05,
    "hobbies": 0.04,
}
_ORDERS_PER_DAY = 17.0
_TICKETS_PER_ORDER = 0.7


def generate_history(store: RetailSnapshot, world: WorldConfig, seed: int) -> WorldHistory:
    placed_at: dict[str, datetime] = {}
    shipments: list[Shipment] = []
    refunds: list[Refund] = []
    for order in store.orders.values():
        placed, order_shipments, order_refunds = _order_history(order, world, seed)
        placed_at[order.order_id] = placed
        shipments.extend(order_shipments)
        refunds.extend(order_refunds)
    return WorldHistory(
        placed_at=placed_at,
        shipments=tuple(shipments),
        refunds=tuple(refunds),
        kpis=tuple(generate_kpis(store, world, seed)),
    )


def choose_carrier(world: WorldConfig, seed: int, tracking_id: str) -> CarrierSpec:
    draw = rng(seed, "carrier", tracking_id).random()
    total = 0.0
    for carrier in world.carriers:
        total += carrier.share
        if draw < total:
            return carrier
    return world.carriers[-1]


def planned_transit(carrier: CarrierSpec, seed: int, tracking_id: str) -> timedelta:
    draw = rng(seed, "transit", tracking_id)
    fastest, slowest = carrier.transit_days
    if draw.random() < carrier.on_time_rate:
        days = draw.uniform(fastest, slowest)
    else:
        days = slowest + draw.uniform(*LATE_DELAY_DAYS)
    return _whole_minute(days * DAY)


def promised_arrival(carrier: CarrierSpec, shipped_at: datetime) -> datetime:
    return shipped_at + carrier.transit_days[1] * DAY


def _order_history(order: Order, world: WorldConfig, seed: int) -> tuple[datetime, list[Shipment], list[Refund]]:
    anchor = world.anchor
    draw = rng(seed, "order", order.order_id)
    tracking_ids = [tracking_id for fulfillment in order.fulfillments for tracking_id in fulfillment.tracking_id]
    region = world.region_of(order.address.state)

    def shipment(tracking_id: str, status: str, **times: datetime | None) -> Shipment:
        carrier = choose_carrier(world, seed, tracking_id)
        return Shipment.model_validate(
            {
                "tracking_id": tracking_id,
                "order_id": order.order_id,
                "carrier": carrier.id,
                "state": order.address.state,
                "region": region,
                "status": status,
                **times,
            }
        )

    if "pending" in order.status:
        return _minute(anchor - draw.uniform(1, 36) * HOUR), [], []

    if order.status == "cancelled":
        placed = _minute(anchor - draw.uniform(2, 60) * DAY)
        cancelled = _minute(placed + draw.uniform(1, 20) * HOUR)
        refunds = [
            Refund(
                refund_id=f"rf_{order.order_id.lstrip('#')}_{position}",
                order_id=order.order_id,
                amount=payment.amount,
                payment_method_id=payment.payment_method_id,
                reason="order cancelled",
                created_at=cancelled,
            )
            for position, payment in enumerate(order.payment_history)
            if payment.transaction_type == "refund"
        ]
        return placed, [shipment(tracking_id, "cancelled") for tracking_id in tracking_ids], refunds

    if order.status == "processed":
        shipments: list[Shipment] = []
        earliest_placed = anchor
        for tracking_id in tracking_ids:
            carrier = choose_carrier(world, seed, tracking_id)
            transit = planned_transit(carrier, seed, tracking_id)
            shipped = _minute(anchor - transit * draw.uniform(0.15, 0.85))
            earliest_placed = min(earliest_placed, _minute(shipped - draw.uniform(6, 30) * HOUR))
            shipments.append(
                shipment(tracking_id, "in_transit", shipped_at=shipped, promised_at=promised_arrival(carrier, shipped))
            )
        return earliest_placed, shipments, []

    placed = _minute(anchor - draw.uniform(12, 60) * DAY)
    shipped = _minute(placed + draw.uniform(6, 30) * HOUR)
    delivered_shipments = []
    for tracking_id in tracking_ids:
        carrier = choose_carrier(world, seed, tracking_id)
        delivered_shipments.append(
            shipment(
                tracking_id,
                "delivered",
                shipped_at=shipped,
                promised_at=promised_arrival(carrier, shipped),
                delivered_at=shipped + planned_transit(carrier, seed, tracking_id),
            )
        )
    return placed, delivered_shipments, []


def generate_kpis(store: RetailSnapshot, world: WorldConfig, seed: int) -> list[KpiPoint]:
    zone = ZoneInfo(world.clock.timezone)
    last_day = world.anchor.astimezone(zone).date() - timedelta(days=1)
    category_share = _category_shares(store, world)
    region_share = _region_shares(store, world)
    points: list[KpiPoint] = []
    for offset in range(world.clock.history_days, 0, -1):
        day = last_day - timedelta(days=offset - 1)
        rhythm = _WEEKLY_RHYTHM[day.weekday()]
        points.extend(_day_kpis(day, rhythm, world, category_share, region_share, seed))
    return points


def _day_kpis(
    day: date,
    rhythm: float,
    world: WorldConfig,
    category_share: dict[str, float],
    region_share: dict[str, float],
    seed: int,
) -> list[KpiPoint]:
    points: list[KpiPoint] = []

    def add(metric: KpiMetric, dimension: KpiDimension, key: str, value: float, samples: int) -> None:
        points.append(
            KpiPoint(day=day, metric=metric, dimension=dimension, key=key, value=round(value, 4), samples=samples)
        )

    def noisy(base: float, spread: float, *labels: object) -> float:
        return base * math.exp(rng(seed, "kpi", day, *labels).gauss(0, spread))

    orders = max(1, round(noisy(_ORDERS_PER_DAY * rhythm, 0.18, "orders")))
    deliveries = max(1, round(noisy(_ORDERS_PER_DAY, 0.15, "deliveries")))
    tickets = max(1, round(noisy(_ORDERS_PER_DAY * _TICKETS_PER_ORDER * rhythm, 0.2, "tickets")))
    late_rates = {
        carrier.id: min(0.9, noisy(1 - carrier.on_time_rate, 0.25, "late", carrier.id)) for carrier in world.carriers
    }
    store_late = sum(carrier.share * late_rates[carrier.id] for carrier in world.carriers)

    add("orders", "store", "all", orders, orders)
    add("deliveries", "store", "all", deliveries, deliveries)
    add("late_delivery_rate", "store", "all", store_late, deliveries)
    add("delivery_delay_hours", "store", "all", noisy(30.0, 0.2, "delay"), round(deliveries * store_late))
    add("refund_rate", "store", "all", noisy(0.08, 0.2, "refunds"), orders)
    add("tickets", "store", "all", tickets, tickets)
    add("resolution_minutes", "store", "all", noisy(42.0, 0.15, "resolution"), tickets)
    add("csat", "store", "all", min(5.0, noisy(4.3, 0.03, "csat")), tickets)

    for carrier in world.carriers:
        carried = max(1, round(deliveries * carrier.share))
        add("deliveries", "carrier", carrier.id, carried, carried)
        add("late_delivery_rate", "carrier", carrier.id, late_rates[carrier.id], carried)
        add(
            "delivery_delay_hours",
            "carrier",
            carrier.id,
            noisy(24.0 * sum(LATE_DELAY_DAYS) / 2, 0.2, "delay", carrier.id),
            carried,
        )

    for category, share in category_share.items():
        category_orders = max(0, round(orders * share))
        category_tickets = max(0, round(tickets * share))
        add("orders", "category", category, category_orders, category_orders)
        add(
            "refund_rate",
            "category",
            category,
            noisy(_CATEGORY_REFUND_RATE[category], 0.25, "refunds", category),
            category_orders,
        )
        add("tickets", "category", category, category_tickets, category_tickets)
        add("csat", "category", category, min(5.0, noisy(4.3, 0.05, "csat", category)), category_tickets)

    for region, share in region_share.items():
        region_deliveries = max(0, round(deliveries * share))
        add("deliveries", "region", region, region_deliveries, region_deliveries)
        add("late_delivery_rate", "region", region, min(0.9, noisy(store_late, 0.2, "late", region)), region_deliveries)
    return points


def _category_shares(store: RetailSnapshot, world: WorldConfig) -> dict[str, float]:
    counts = Counter(
        world.category_of(store.products[item.product_id].name)
        for order in store.orders.values()
        for item in order.items
    )
    total = sum(counts.values())
    return {category: counts[category] / total for category in world.categories}


def _region_shares(store: RetailSnapshot, world: WorldConfig) -> dict[str, float]:
    counts = Counter(world.region_of(order.address.state) for order in store.orders.values())
    total = sum(counts.values())
    return {region: counts[region] / total for region in world.regions}


def _minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def _whole_minute(duration: timedelta) -> timedelta:
    return timedelta(minutes=round(duration.total_seconds() / 60))
