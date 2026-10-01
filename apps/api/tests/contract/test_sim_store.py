from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory import MemorySimStore
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgSimStore
from ahq.domain import NotFoundError
from ahq.domain.sim import DayEnded, ParcelDelivered, ScriptEntry, SimRun
from ahq.ports import SimStore

START = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def a_run(run_id: str = "sim_1", *, created: datetime = START) -> SimRun:
    return SimRun(
        run_id=run_id,
        scenario="normal-day",
        seed=7,
        status="running",
        started_at=START,
        ends_at=START + timedelta(days=1),
        sim_now=START,
        tick_no=0,
        tick_minutes=5,
        tick_seconds=2.0,
        created_at=created,
        updated_at=created,
    )


SCRIPT = [
    ScriptEntry(seq=0, due_at=START + timedelta(minutes=5), effect=ParcelDelivered(tracking_id="t1", order_id="#o1")),
    ScriptEntry(seq=1, due_at=START + timedelta(minutes=5), effect=ParcelDelivered(tracking_id="t2", order_id="#o2")),
    ScriptEntry(seq=2, due_at=START + timedelta(days=1), effect=DayEnded()),
]


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
async def runs(request: pytest.FixtureRequest) -> AsyncIterator[SimStore]:
    clock = ManualClock()
    if request.param == "memory":
        yield MemorySimStore(clock)
        return
    engine = make_engine(request.getfixturevalue("clean_db"))
    yield PgSimStore(make_sessionmaker(engine), clock)
    await engine.dispose()


async def test_runs_are_stored_with_their_scripts(runs: SimStore) -> None:
    await runs.create(a_run(), SCRIPT)
    await runs.create(a_run("sim_2", created=START + timedelta(hours=1)), [])
    assert await runs.get("sim_1") == a_run()
    assert await runs.get("sim_missing") is None
    latest = await runs.latest()
    assert latest is not None
    assert latest.run_id == "sim_2"


async def test_entries_are_due_in_a_half_open_window(runs: SimStore) -> None:
    await runs.create(a_run(), SCRIPT)
    assert await runs.due("sim_1", after=START, until=START + timedelta(minutes=4)) == []
    assert await runs.due("sim_1", after=START, until=START + timedelta(minutes=5)) == SCRIPT[:2]
    assert await runs.due("sim_1", after=START + timedelta(minutes=5), until=START + timedelta(days=1)) == SCRIPT[2:]


async def test_only_one_delivery_advances_a_tick(runs: SimStore) -> None:
    await runs.create(a_run(), SCRIPT)
    later = START + timedelta(minutes=5)
    advanced = await runs.advance("sim_1", from_tick=0, sim_now=later, status="running")
    assert advanced is not None
    assert (advanced.tick_no, advanced.sim_now) == (1, later)
    assert await runs.advance("sim_1", from_tick=0, sim_now=later, status="running") is None


async def test_a_paused_run_does_not_advance(runs: SimStore) -> None:
    await runs.create(a_run(), SCRIPT)
    paused = await runs.set_status("sim_1", "paused")
    assert paused.status == "paused"
    assert await runs.advance("sim_1", from_tick=0, sim_now=START, status="running") is None
    with pytest.raises(NotFoundError):
        await runs.set_status("sim_missing", "paused")
