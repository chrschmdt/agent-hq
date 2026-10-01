from __future__ import annotations

from ahq.domain import EventKind, NewEvent, WorkItemId
from tests.contract.conftest import Stores


def event(kind: EventKind, work_item_id: str | None = None, stores: Stores | None = None) -> NewEvent:
    assert stores is not None
    return NewEvent(
        kind=kind,
        occurred_at=stores.clock.now(),
        work_item_id=WorkItemId(work_item_id) if work_item_id else None,
        payload={"k": kind.value},
    )


async def test_append_assigns_increasing_ids(stores: Stores) -> None:
    stored = await stores.events.append(
        [event(EventKind.WORK_CREATED, stores=stores), event(EventKind.WORK_STARTED, stores=stores)]
    )
    assert [e.id for e in stored] == sorted(e.id for e in stored)
    assert stored[1].id > stored[0].id


async def test_read_after_follows_the_cursor(stores: Stores) -> None:
    first, second, third = await stores.events.append(
        [
            event(kind, stores=stores)
            for kind in (EventKind.WORK_CREATED, EventKind.WORK_STARTED, EventKind.WORK_COMPLETED)
        ]
    )
    assert [e.id for e in await stores.events.read_after(0)] == [first.id, second.id, third.id]
    assert [e.id for e in await stores.events.read_after(first.id)] == [second.id, third.id]
    assert [e.id for e in await stores.events.read_after(first.id, limit=1)] == [second.id]
    assert await stores.events.read_after(third.id) == []


async def test_events_round_trip_unchanged(stores: Stores) -> None:
    (stored,) = await stores.events.append([event(EventKind.MODEL_CALLED, "wi_1", stores=stores)])
    (read,) = await stores.events.read_after(stored.id - 1)
    assert read == stored
    assert read.payload == {"k": "model.called"}


async def test_for_work_item_filters_and_orders(stores: Stores) -> None:
    await stores.events.append(
        [
            event(EventKind.WORK_CREATED, "wi_a", stores=stores),
            event(EventKind.WORK_CREATED, "wi_b", stores=stores),
            event(EventKind.WORK_COMPLETED, "wi_a", stores=stores),
        ]
    )
    kinds = [e.kind for e in await stores.events.for_work_item(WorkItemId("wi_a"))]
    assert kinds == [EventKind.WORK_CREATED, EventKind.WORK_COMPLETED]


async def test_last_id_tracks_the_newest_event(stores: Stores) -> None:
    assert await stores.events.last_id() == 0
    stored = await stores.events.append([event(EventKind.WORK_CREATED, stores=stores)])
    assert await stores.events.last_id() == stored[-1].id


async def test_recent_returns_the_newest_matching_events_first(stores: Stores) -> None:
    await stores.events.append(
        [
            event(EventKind.WORK_CREATED, "wi_a", stores=stores),
            NewEvent(kind=EventKind.MODEL_CALLED, occurred_at=stores.clock.now(), actor="ops", payload={}),
            NewEvent(kind=EventKind.MODEL_CALLED, occurred_at=stores.clock.now(), actor="support", payload={}),
            event(EventKind.WORK_COMPLETED, "wi_a", stores=stores),
        ]
    )
    assert [e.kind for e in await stores.events.recent(limit=2)] == [EventKind.WORK_COMPLETED, EventKind.MODEL_CALLED]
    by_ops = await stores.events.recent(actor="ops")
    assert [(e.kind, e.actor) for e in by_ops] == [(EventKind.MODEL_CALLED, "ops")]
    work = await stores.events.recent(kinds={EventKind.WORK_CREATED, EventKind.WORK_COMPLETED})
    assert [e.kind for e in work] == [EventKind.WORK_COMPLETED, EventKind.WORK_CREATED]
