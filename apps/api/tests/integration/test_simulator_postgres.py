from __future__ import annotations

from collections import Counter
from datetime import datetime

import pytest
from pydantic import JsonValue

from ahq.adapters.clock import ManualClock
from ahq.config import load_world_config
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgBaseline, PgEventLog, PgRetailRepo, PgSimStore, PgWorldRepo
from ahq.domain.retail import RetailSnapshot
from ahq.retail import canonical_hash
from ahq.sim.control import SimControl
from ahq.sim.seed import seed_world
from ahq.sim.tick import SimDeps
from tests.conftest import TAU3_DIR

pytestmark = pytest.mark.db
EFFECTS = {"ticket.opened", "parcel.delivered", "order.shipped"}


async def test_a_seeded_day_replays_exactly_and_resets(clean_db: str, tau3_snapshot: RetailSnapshot) -> None:
    engine = make_engine(clean_db)
    sessions = make_sessionmaker(engine)
    config = load_world_config()
    retail, world, events = PgRetailRepo(sessions), PgWorldRepo(sessions), PgEventLog(sessions)
    baseline = PgBaseline(sessions)
    try:
        await seed_world(retail, world, tau3_snapshot, config, seed=7, content_dir=TAU3_DIR / "no-content")
        await baseline.capture()
        seeded = canonical_hash(await retail.snapshot())
        clock = ManualClock()
        deps = SimDeps(
            runs=PgSimStore(sessions, clock), retail=retail, world=world, events=events, clock=clock, config=config
        )
        control = SimControl(deps, baseline, queue=None)

        async def play() -> tuple[list[tuple[str, datetime, dict[str, JsonValue]]], str]:
            cursor = await events.last_id()
            run = await control.start("normal-day", seed=7, schedule=False)
            finished = await control.drive(run.run_id)
            assert finished.status == "finished"
            played = [
                (e.kind.value, e.occurred_at, e.payload)
                for e in await events.read_after(cursor, limit=100_000)
                if e.kind.value in EFFECTS
            ]
            return played, canonical_hash(await retail.snapshot())

        first_events, first_store = await play()
        second_events, second_store = await play()
        assert Counter(kind for kind, _, _ in first_events)["ticket.opened"] == 150
        assert second_events == first_events
        assert second_store == first_store != seeded

        await control.reset()
        assert canonical_hash(await retail.snapshot()) == seeded
        assert await world.ticket("tk_7_0000") is None
    finally:
        await engine.dispose()
