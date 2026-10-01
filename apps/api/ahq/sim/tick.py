from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from pydantic import JsonValue

from ahq.config import WorldConfig
from ahq.domain import AgentVersion, EventKind, KpiAlert, NewEvent, WorkItem
from ahq.domain.retail import Fulfillment, RetailChange
from ahq.domain.sim import (
    ArticlePublished,
    CustomerBrief,
    OrderShipped,
    ParcelDelivered,
    ScriptEntry,
    SimRun,
    TicketOpened,
)
from ahq.domain.world import Shipment, Ticket, TicketMessage
from ahq.ports import Clock, EventLog, RetailRepo, SimStore, WorldRepo
from ahq.sim.generate import promised_arrival
from ahq.sim.monitor import WINDOW, check_times, delivery_alerts

ACTOR = "simulator"
MONITOR = "monitor"


class TicketDesk(Protocol):
    async def take(self, ticket: Ticket, brief: CustomerBrief, *, run_id: str, today: date) -> None: ...


class AlertDesk(Protocol):
    async def raise_alert(self, alert: KpiAlert, today: date, *, scope: str, actor: str = MONITOR) -> WorkItem: ...


class ArticleDesk(Protocol):
    async def publish_article(self, doc_id: str, version: int, day: date, *, actor: str = "scenario") -> bool: ...


class DeployDesk(Protocol):
    async def canary_change(
        self, agent: str, *, changes: Mapping[str, JsonValue], pct: int, note: str, by: str
    ) -> AgentVersion: ...


@dataclass(frozen=True)
class SimDeps:
    runs: SimStore
    retail: RetailRepo
    world: WorldRepo
    events: EventLog
    clock: Clock
    config: WorldConfig
    desk: TicketDesk | None = None
    alerts: AlertDesk | None = None
    deploys: DeployDesk | None = None
    articles: ArticleDesk | None = None


async def run_tick(deps: SimDeps, run_id: str, tick_no: int) -> SimRun | None:
    run = await deps.runs.get(run_id)
    if run is None or run.status != "running" or run.tick_no != tick_no:
        return None
    until = min(run.sim_now + run.tick, run.ends_at)
    for entry in await deps.runs.due(run_id, after=run.sim_now, until=until):
        event = await apply(deps, entry, run_id=run.run_id, agent_tickets=run.agent_tickets)
        if event is not None:
            await deps.events.append([event])
    for at in check_times(run.sim_now, until):
        await watch_deliveries(deps, run, at)
    finished = until >= run.ends_at
    advanced = await deps.runs.advance(
        run_id, from_tick=tick_no, sim_now=until, status="finished" if finished else "running"
    )
    if advanced is not None and finished:
        await deps.events.append([control_event(EventKind.SIM_FINISHED, advanced)])
    return advanced


async def apply(deps: SimDeps, entry: ScriptEntry, *, run_id: str = "", agent_tickets: int = 0) -> NewEvent | None:
    effect = entry.effect
    match effect:
        case TicketOpened():
            handed_off = effect.for_agents or _number(effect.ticket_id) < agent_tickets
            return await _open_ticket(deps, entry, effect, run_id=run_id, handed_off=handed_off)
        case ParcelDelivered():
            return await _deliver(deps, entry, effect)
        case OrderShipped():
            return await _ship(deps, entry, effect)
        case ArticlePublished():
            if deps.articles is not None:
                day = deps.config.clock.day_at(entry.due_at)
                await deps.articles.publish_article(effect.doc_id, effect.version, day)
            return None
        case _:
            return None


def _number(ticket_id: str) -> int:
    return int(ticket_id.rsplit("_", 1)[1])


async def _open_ticket(
    deps: SimDeps, entry: ScriptEntry, effect: TicketOpened, *, run_id: str, handed_off: bool
) -> NewEvent | None:
    brief = effect.brief
    ticket = Ticket(
        ticket_id=effect.ticket_id,
        user_id=brief.user_id,
        order_id=brief.order_id,
        product_id=brief.product_id,
        intent=brief.intent,
        subject=brief.subject,
        status="open",
        source="simulation",
        created_at=entry.due_at,
        messages=(TicketMessage(author="customer", body=brief.opening_message, created_at=entry.due_at),),
    )
    if not await deps.world.open_ticket(ticket):
        return None
    if handed_off and deps.desk is not None:
        await deps.desk.take(ticket, brief, run_id=run_id, today=deps.config.clock.day_at(entry.due_at))
    return NewEvent(
        kind=EventKind.TICKET_OPENED,
        occurred_at=entry.due_at,
        actor=ACTOR,
        payload={
            "ticket_id": ticket.ticket_id,
            "intent": brief.intent,
            "subject": ticket.subject,
            "user_id": brief.user_id,
            "order_id": brief.order_id,
            "for_agents": handed_off,
        },
    )


async def _deliver(deps: SimDeps, entry: ScriptEntry, effect: ParcelDelivered) -> NewEvent | None:
    shipment = await deps.world.shipment(effect.tracking_id)
    if shipment is None or shipment.status != "in_transit":
        return None
    async with deps.retail.session() as session:
        order = await session.order(effect.order_id)
        if order is not None and order.status == "processed":
            await session.save(RetailChange(orders=(order.model_copy(update={"status": "delivered"}),)))
    delivered = shipment.model_copy(update={"status": "delivered", "delivered_at": entry.due_at})
    if not await deps.world.save_shipment(delivered):
        return None
    late = shipment.promised_at is not None and entry.due_at > shipment.promised_at
    return NewEvent(
        kind=EventKind.PARCEL_DELIVERED,
        occurred_at=entry.due_at,
        actor=ACTOR,
        payload={
            "tracking_id": shipment.tracking_id,
            "order_id": shipment.order_id,
            "carrier": shipment.carrier,
            "region": shipment.region,
            "late": late,
        },
    )


async def _ship(deps: SimDeps, entry: ScriptEntry, effect: OrderShipped) -> NewEvent | None:
    carrier = next(c for c in deps.config.carriers if c.id == effect.carrier)
    async with deps.retail.session() as session:
        order = await session.order(effect.order_id)
        if order is None or "pending" not in order.status:
            return None
        region = deps.config.region_of(order.address.state)
        await deps.world.save_shipment(
            Shipment(
                tracking_id=effect.tracking_id,
                order_id=order.order_id,
                carrier=carrier.id,
                state=order.address.state,
                region=region,
                status="in_transit",
                shipped_at=entry.due_at,
                promised_at=promised_arrival(carrier, entry.due_at),
            )
        )
        fulfillment = Fulfillment(tracking_id=[effect.tracking_id], item_ids=[item.item_id for item in order.items])
        shipped = order.model_copy(update={"status": "processed", "fulfillments": [*order.fulfillments, fulfillment]})
        await session.save(RetailChange(orders=(shipped,)))
    return NewEvent(
        kind=EventKind.ORDER_SHIPPED,
        occurred_at=entry.due_at,
        actor=ACTOR,
        payload={
            "order_id": order.order_id,
            "tracking_id": effect.tracking_id,
            "carrier": carrier.id,
            "region": region,
        },
    )


async def watch_deliveries(deps: SimDeps, run: SimRun, at: datetime) -> list[KpiAlert]:
    tickets = await deps.world.tickets_opened(at - WINDOW, at)
    alerts = delivery_alerts(tickets, await deps.world.shipments(), at)
    for alert in alerts:
        payload = alert.model_dump(mode="json")
        await deps.events.append([NewEvent(kind=EventKind.KPI_ALERT, occurred_at=at, actor=MONITOR, payload=payload)])
        if run.alerts_to_agents and deps.alerts is not None:
            await deps.alerts.raise_alert(alert, deps.config.clock.day_at(at), scope=run.run_id)
    return alerts


def control_event(kind: EventKind, run: SimRun) -> NewEvent:
    return NewEvent(
        kind=kind,
        occurred_at=run.sim_now,
        actor=ACTOR,
        payload={
            "run_id": run.run_id,
            "scenario": run.scenario,
            "seed": run.seed,
            "tick_no": run.tick_no,
            "tick_minutes": run.tick_minutes,
            "tick_seconds": run.tick_seconds,
        },
    )
