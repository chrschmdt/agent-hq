from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from ahq.config import WorldConfig
from ahq.domain.retail import RetailSnapshot
from ahq.domain.sim import (
    ArticlePublished,
    BriefIntent,
    CustomerBrief,
    DayEnded,
    OrderShipped,
    ParcelDelivered,
    ScriptEffect,
    ScriptEntry,
    TicketOpened,
)
from ahq.domain.world import Shipment
from ahq.sim.briefs import make_briefs, stuck_parcel_brief, wave_briefs
from ahq.sim.generate import choose_carrier, planned_transit
from ahq.sim.scenarios import ArticleUpload, CarrierDelay, Scenario, Wave
from ahq.sim.seeded import rng
from ahq.sim.traffic import arrival_times

PROCESSING_HOURS = (30.0, 96.0)
HOLD_INTENTS: frozenset[BriefIntent] = frozenset(
    {"cancel_order", "change_order_address", "change_order_items", "change_payment"}
)
_ORDER = {"article.published": 0, "day.ended": 3, "order.shipped": 1, "parcel.delivered": 0, "ticket.opened": 2}


def build_script(
    scenario: Scenario,
    store: RetailSnapshot,
    shipments: Mapping[str, Shipment],
    placed_at: Mapping[str, datetime],
    world: WorldConfig,
    *,
    seed: int,
    start: datetime,
    end: datetime,
) -> list[ScriptEntry]:
    effects: list[tuple[datetime, ScriptEffect]] = []

    used: set[str] = set()
    briefs = make_briefs(store, scenario.intents, scenario.tickets, seed=seed, used=used)
    moments = arrival_times(len(briefs), start, end, timezone=world.clock.timezone, seed=seed)
    for index, (brief, moment) in enumerate(zip(briefs, moments, strict=True)):
        effects.append((moment, TicketOpened(ticket_id=f"tk_{seed}_{index:04d}", brief=brief)))
    for number, wave in enumerate(scenario.waves):
        if wave.kind == "mix":
            extra = make_briefs(
                store, scenario.intents, wave.tickets, seed=seed, used=used, stream=f"wave:{number}", first=len(briefs)
            )
        else:
            extra = wave_briefs(store, wave.kind, wave.tickets, seed=seed, used=used, first=len(briefs))
        effects += _wave(wave, number, extra, len(briefs), world, seed=seed, start=start)
        briefs += extra
    if scenario.upload is not None:
        effects.append((_at(scenario.upload.at, world, start), _publish(scenario.upload)))

    for shipment in shipments.values():
        if shipment.status != "in_transit" or shipment.shipped_at is None:
            continue
        carrier = choose_carrier(world, seed, shipment.tracking_id)
        arrival = shipment.shipped_at + planned_transit(carrier, seed, shipment.tracking_id)
        if start < arrival <= end:
            effects.append((arrival, ParcelDelivered(tracking_id=shipment.tracking_id, order_id=shipment.order_id)))

    held = {brief.order_id for brief in briefs if brief.intent in HOLD_INTENTS}
    for order in store.orders.values():
        placed = placed_at.get(order.order_id)
        if "pending" not in order.status or placed is None or order.order_id in held:
            continue
        ship_at = _whole_minute(
            placed + timedelta(hours=rng(seed, "processing", order.order_id).uniform(*PROCESSING_HOURS))
        )
        if start < ship_at <= end:
            tracking_id = tracking_number(seed, order.order_id)
            carrier = choose_carrier(world, seed, tracking_id)
            effects.append(
                (ship_at, OrderShipped(order_id=order.order_id, tracking_id=tracking_id, carrier=carrier.id))
            )

    if scenario.delay is not None:
        effects = _delay_carrier(scenario.delay, effects, briefs, store, shipments, world, seed=seed, start=start)
    effects.append((end, DayEnded()))
    effects.sort(key=lambda pair: (pair[0], _ORDER[pair[1].kind], _identity(pair[1])))
    return [ScriptEntry(seq=seq, due_at=moment, effect=effect) for seq, (moment, effect) in enumerate(effects)]


def _wave(
    wave: Wave,
    number: int,
    briefs: Sequence[CustomerBrief],
    first: int,
    world: WorldConfig,
    *,
    seed: int,
    start: datetime,
) -> list[tuple[datetime, ScriptEffect]]:
    begins = _at(wave.starts, world, start)
    draw = rng(seed, "wave-times", str(number))
    moments = sorted(begins + timedelta(minutes=draw.randrange(wave.minutes)) for _ in briefs)
    return [
        (moment, TicketOpened(ticket_id=f"tk_{seed}_{first + n:04d}", brief=brief, for_agents=True))
        for n, (brief, moment) in enumerate(zip(briefs, moments, strict=True))
    ]


def _at(moment: time, world: WorldConfig, start: datetime) -> datetime:
    local = start.astimezone(ZoneInfo(world.clock.timezone))
    return local.replace(hour=moment.hour, minute=moment.minute, second=0, microsecond=0)


def _publish(upload: ArticleUpload) -> ArticlePublished:
    return ArticlePublished(doc_id=upload.doc_id, version=upload.version)


def _delay_carrier(
    delay: CarrierDelay,
    effects: list[tuple[datetime, ScriptEffect]],
    briefs: Sequence[CustomerBrief],
    store: RetailSnapshot,
    shipments: Mapping[str, Shipment],
    world: WorldConfig,
    *,
    seed: int,
    start: datetime,
) -> list[tuple[datetime, ScriptEffect]]:
    local = start.astimezone(ZoneInfo(world.clock.timezone))
    begins = local.replace(hour=delay.starts.hour, minute=delay.starts.minute, second=0, microsecond=0)
    stuck = {
        tracking_id: shipment
        for tracking_id, shipment in sorted(shipments.items())
        if shipment.status == "in_transit" and (shipment.carrier, shipment.region) == (delay.carrier, delay.region)
    }
    kept = [
        (moment, effect)
        for moment, effect in effects
        if not (isinstance(effect, ParcelDelivered) and effect.tracking_id in stuck and moment >= begins)
    ]
    carrier = next(c.name for c in world.carriers if c.id == delay.carrier)
    already_writing = {brief.order_id for brief in briefs}
    index = len(briefs)
    for shipment in stuck.values():
        order = store.orders.get(shipment.order_id)
        draw = rng(seed, "delay", shipment.tracking_id)
        if order is None or order.order_id in already_writing or draw.random() >= delay.contact_share:
            continue
        moment = _whole_minute(begins + draw.uniform(0.05, 1.0) * delay.contact_within)
        brief = stuck_parcel_brief(store, order, f"br_{seed}_{index:04d}", seed=seed, carrier=carrier)
        kept.append((moment, TicketOpened(ticket_id=f"tk_{seed}_{index:04d}", brief=brief)))
        index += 1
    return kept


def tracking_number(seed: int, order_id: str) -> str:
    return str(rng(seed, "tracking", order_id).randrange(10**11, 10**12))


def _identity(effect: ScriptEffect) -> str:
    match effect:
        case TicketOpened():
            return effect.ticket_id
        case ParcelDelivered():
            return effect.tracking_id
        case OrderShipped():
            return effect.order_id
        case ArticlePublished():
            return f"{effect.doc_id}@{effect.version}"
        case DayEnded():
            return ""


def _whole_minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)
