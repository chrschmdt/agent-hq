from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory import MemoryBaseline, MemoryEventLog, MemorySimStore, MemoryWorldRepo
from ahq.adapters.queue_inprocess import InProcessQueue
from ahq.config import load_world_config
from ahq.domain import Event, Job, SimTickJob, Topic
from ahq.domain.retail import RetailSnapshot
from ahq.domain.sim import CustomerBrief, TicketOpened
from ahq.domain.world import Ticket
from ahq.ports import Delivery
from ahq.retail import InMemoryRetailRepo, canonical_hash
from ahq.sim.control import SimControl
from ahq.sim.generate import generate_history
from ahq.sim.tick import SimDeps, apply, run_tick

EFFECTS = {"ticket.opened", "parcel.delivered", "order.shipped"}


@dataclass
class Simulator:
    control: SimControl
    deps: SimDeps
    retail: InMemoryRetailRepo
    world: MemoryWorldRepo
    events: MemoryEventLog
    queue: InProcessQueue

    async def all_events(self) -> list[Event]:
        return await self.events.read_after(0, limit=100_000)

    async def effect_events(self) -> list[tuple[str, Any, Any]]:
        return [(e.kind.value, e.occurred_at, e.payload) for e in await self.all_events() if e.kind.value in EFFECTS]


@pytest.fixture
async def sim(tau3_snapshot: RetailSnapshot) -> Simulator:
    config = load_world_config()
    clock = ManualClock()
    retail = InMemoryRetailRepo(tau3_snapshot)
    world = MemoryWorldRepo()
    await world.load(generate_history(tau3_snapshot, config, seed=7))
    baseline = MemoryBaseline(retail, world)
    await baseline.capture()
    events = MemoryEventLog()
    queue = InProcessQueue()
    deps = SimDeps(runs=MemorySimStore(clock), retail=retail, world=world, events=events, clock=clock, config=config)
    control = SimControl(deps, baseline, queue)

    async def handle(job: Job, delivery: Delivery) -> None:
        await control.tick(SimTickJob.model_validate(job.model_dump()))

    queue.register(Topic.SIM, handle)
    return Simulator(control, deps, retail, world, events, queue)


async def test_a_fast_day_plays_every_entry_and_ends_on_time(sim: Simulator) -> None:
    run = await sim.control.start("normal-day", seed=7, schedule=False)
    finished = await sim.control.drive(run.run_id)
    assert finished.status == "finished"
    assert finished.sim_now == run.ends_at
    assert finished.tick_no == 288

    kinds = Counter(event.kind.value for event in await sim.all_events())
    assert kinds["ticket.opened"] == 150
    assert kinds["parcel.delivered"] > 0
    assert kinds["order.shipped"] > 0
    assert (kinds["sim.started"], kinds["sim.finished"]) == (1, 1)

    store = await sim.retail.snapshot()
    for event in await sim.all_events():
        payload = event.payload
        if event.kind.value == "ticket.opened":
            ticket = await sim.world.ticket(str(payload["ticket_id"]))
            assert ticket is not None
            assert ticket.messages[0].author == "customer"
        elif event.kind.value == "parcel.delivered":
            assert store.orders[str(payload["order_id"])].status == "delivered"
        elif event.kind.value == "order.shipped":
            order = store.orders[str(payload["order_id"])]
            assert order.status == "processed"
            assert order.fulfillments[-1].tracking_id == [payload["tracking_id"]]
    assert all(run.started_at < e.occurred_at <= run.ends_at for e in await sim.all_events() if e.kind.value in EFFECTS)


async def test_the_same_seed_plays_the_same_day(sim: Simulator) -> None:
    first = await sim.control.start("normal-day", seed=7, schedule=False)
    await sim.control.drive(first.run_id)
    first_events = await sim.effect_events()
    first_store = canonical_hash(await sim.retail.snapshot())

    second = await sim.control.start("normal-day", seed=7, schedule=False)
    await sim.control.drive(second.run_id)
    second_events = (await sim.effect_events())[len(first_events) :]
    assert second_events == first_events
    assert canonical_hash(await sim.retail.snapshot()) == first_store

    other = await sim.control.start("normal-day", seed=8, schedule=False)
    await sim.control.drive(other.run_id)
    assert (await sim.effect_events())[len(first_events) * 2 :] != first_events


async def test_a_stale_or_repeated_tick_changes_nothing(sim: Simulator) -> None:
    run = await sim.control.start("normal-day", seed=7, schedule=False)
    advanced = await run_tick(sim.deps, run.run_id, 0)
    assert advanced is not None
    assert advanced.tick_no == 1
    before = await sim.all_events()
    assert await run_tick(sim.deps, run.run_id, 0) is None
    assert await sim.all_events() == before


async def test_ticks_chain_through_the_queue_and_pause_and_resume(sim: Simulator) -> None:
    run = await sim.control.start("normal-day", seed=7, tick_seconds=2.0)
    await sim.control.pause(run.run_id)
    await sim.queue.run_until_idle()
    paused = await sim.deps.runs.get(run.run_id)
    assert paused is not None
    assert (paused.status, paused.tick_no) == ("paused", 0)

    await sim.control.resume(run.run_id)
    await sim.queue.run_until_idle()
    done = await sim.deps.runs.get(run.run_id)
    assert done is not None
    assert (done.status, done.tick_no) == ("finished", 288)


async def test_reset_puts_the_store_back(sim: Simulator, tau3_snapshot: RetailSnapshot) -> None:
    run = await sim.control.start("normal-day", seed=7, schedule=False)
    await sim.control.drive(run.run_id)
    assert canonical_hash(await sim.retail.snapshot()) != canonical_hash(tau3_snapshot)
    await sim.control.reset()
    assert canonical_hash(await sim.retail.snapshot()) == canonical_hash(tau3_snapshot)
    assert await sim.world.ticket("tk_7_0000") is None


async def test_starting_again_stops_the_active_run(sim: Simulator) -> None:
    first = await sim.control.start("normal-day", seed=7, schedule=False)
    await sim.control.start("normal-day", seed=7, schedule=False)
    stopped = await sim.deps.runs.get(first.run_id)
    assert stopped is not None
    assert stopped.status == "stopped"
    assert await run_tick(sim.deps, first.run_id, 0) is None


async def test_a_surge_brings_ten_times_the_noon_customers_and_hands_them_all_to_the_agents(sim: Simulator) -> None:
    taken: list[str] = []

    class Desk:
        async def take(self, ticket: Ticket, brief: CustomerBrief, *, run_id: str, today: date) -> None:
            taken.append(ticket.ticket_id)

    baseline = MemoryBaseline(sim.retail, sim.world)
    await baseline.capture()
    sim.control = SimControl(replace(sim.deps, desk=Desk()), baseline, sim.queue)
    run = await sim.control.start("surge", seed=7, schedule=False)
    await sim.control.drive(run.run_id)
    zone = ZoneInfo(load_world_config().clock.timezone)
    opened = [e for e in await sim.all_events() if e.kind.value == "ticket.opened"]
    noon = [e for e in opened if e.occurred_at.astimezone(zone).hour == 12]
    assert len(opened) == 150
    assert len(noon) >= 60
    assert len(taken) == 60
    assert all(ticket_id >= "tk_7_0090" for ticket_id in taken)


async def test_an_evening_ticket_goes_to_the_agents_on_the_stores_day_not_the_next_utc_day(sim: Simulator) -> None:
    days: list[date] = []

    class Desk:
        async def take(self, ticket: Ticket, brief: CustomerBrief, *, run_id: str, today: date) -> None:
            days.append(today)

    run = await sim.control.start("normal-day", seed=7, schedule=False)
    zone = ZoneInfo(load_world_config().clock.timezone)
    script = await sim.deps.runs.due(run.run_id, after=run.started_at - timedelta(seconds=1), until=run.ends_at)
    evening = next(
        entry for entry in script if isinstance(entry.effect, TicketOpened) and entry.due_at.astimezone(zone).hour >= 20
    )
    stored = evening.model_copy(update={"due_at": evening.due_at.astimezone(UTC)})
    assert stored.due_at.date() == date(2026, 6, 16)
    await apply(replace(sim.deps, desk=Desk()), stored, run_id=run.run_id, agent_tickets=200)
    assert days == [date(2026, 6, 15)]
