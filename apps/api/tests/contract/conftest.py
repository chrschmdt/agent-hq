from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory import MemoryApprovalStore, MemoryEventLog, MemoryWorkStore
from ahq.db.engine import make_engine, make_sessionmaker
from ahq.db.repos import PgApprovalStore, PgEventLog, PgWorkStore
from ahq.ports import ApprovalStore, EventLog, WorkStore


@dataclass
class Stores:
    events: EventLog
    work: WorkStore
    approvals: ApprovalStore
    clock: ManualClock


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
async def stores(request: pytest.FixtureRequest) -> AsyncIterator[Stores]:
    clock = ManualClock()
    if request.param == "memory":
        yield Stores(MemoryEventLog(), MemoryWorkStore(clock), MemoryApprovalStore(clock), clock)
        return
    url: str = request.getfixturevalue("clean_db")
    engine = make_engine(url)
    sessions = make_sessionmaker(engine)
    yield Stores(PgEventLog(sessions), PgWorkStore(sessions, clock), PgApprovalStore(sessions, clock), clock)
    await engine.dispose()
