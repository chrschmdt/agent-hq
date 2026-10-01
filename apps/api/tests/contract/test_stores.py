from __future__ import annotations

from datetime import timedelta

import pytest

from ahq.domain import (
    ApprovalDecision,
    ApprovalId,
    ApprovalRequest,
    ApprovalStatus,
    ConflictError,
    NotFoundError,
    WorkItemId,
    WorkKind,
    WorkStatus,
)
from tests.contract.conftest import Stores

REQUEST = ApprovalRequest(action="refund", arguments={"amount": 120.0}, reason="over threshold")


async def test_created_items_start_new_with_their_own_thread(stores: Stores) -> None:
    first = await stores.work.create(WorkKind.SMOKE, {"note": "a"})
    second = await stores.work.create(WorkKind.SMOKE, {})
    assert first.status is WorkStatus.NEW
    assert first.thread_id != second.thread_id
    assert await stores.work.get(first.id) == first


async def test_unknown_items_raise_not_found(stores: Stores) -> None:
    with pytest.raises(NotFoundError):
        await stores.work.get(WorkItemId("wi_missing"))


async def test_running_counts_an_attempt_and_errors_are_kept(stores: Stores) -> None:
    item = await stores.work.create(WorkKind.SMOKE, {})
    running = await stores.work.set_status(item.id, WorkStatus.RUNNING)
    failed = await stores.work.set_status(item.id, WorkStatus.FAILED, error="boom")
    assert running.attempts == 1
    assert failed.last_error == "boom"
    assert failed.attempts == 1


async def test_count_active_counts_new_and_running(stores: Stores) -> None:
    a = await stores.work.create(WorkKind.SMOKE, {})
    b = await stores.work.create(WorkKind.SMOKE, {})
    await stores.work.create(WorkKind.SMOKE, {})
    await stores.work.set_status(a.id, WorkStatus.RUNNING)
    await stores.work.set_status(b.id, WorkStatus.DONE)
    assert await stores.work.count_active() == 2


async def test_a_lease_excludes_other_owners_until_it_expires(stores: Stores) -> None:
    item = await stores.work.create(WorkKind.SMOKE, {})
    assert await stores.work.acquire_lease(item.id, "a", timedelta(seconds=30))
    assert not await stores.work.acquire_lease(item.id, "b", timedelta(seconds=30))
    assert await stores.work.acquire_lease(item.id, "a", timedelta(seconds=30))
    stores.clock.advance(timedelta(seconds=31))
    assert await stores.work.acquire_lease(item.id, "b", timedelta(seconds=30))


async def test_releasing_a_lease_lets_another_owner_in(stores: Stores) -> None:
    item = await stores.work.create(WorkKind.SMOKE, {})
    assert await stores.work.acquire_lease(item.id, "a", timedelta(minutes=5))
    await stores.work.release_lease(item.id, "b")
    assert not await stores.work.acquire_lease(item.id, "b", timedelta(minutes=5))
    await stores.work.release_lease(item.id, "a")
    assert await stores.work.acquire_lease(item.id, "b", timedelta(minutes=5))


async def test_opening_the_same_interrupt_twice_returns_one_approval(stores: Stores) -> None:
    item = await stores.work.create(WorkKind.SMOKE, {})
    first = await stores.approvals.open(item.id, "int_1", REQUEST)
    again = await stores.approvals.open(item.id, "int_1", REQUEST)
    assert again.id == first.id
    assert first.status is ApprovalStatus.PENDING
    assert first.request == REQUEST
    assert [a.id for a in await stores.approvals.pending()] == [first.id]


async def test_a_decision_is_recorded_once(stores: Stores) -> None:
    item = await stores.work.create(WorkKind.SMOKE, {})
    approval = await stores.approvals.open(item.id, "int_1", REQUEST)
    edit = ApprovalDecision(verdict="edit", arguments={"amount": 100.0}, note="cap at 100")
    decided = await stores.approvals.decide(approval.id, edit, "operator")
    assert decided.status is ApprovalStatus.EDITED
    assert decided.decision == edit
    assert decided.decided_by == "operator"
    assert await stores.approvals.pending() == []
    with pytest.raises(ConflictError):
        await stores.approvals.decide(approval.id, ApprovalDecision(verdict="approve"), "operator")


async def test_unknown_approvals_raise_not_found(stores: Stores) -> None:
    with pytest.raises(NotFoundError):
        await stores.approvals.get(ApprovalId("apv_missing"))
    with pytest.raises(NotFoundError):
        await stores.approvals.decide(ApprovalId("apv_missing"), ApprovalDecision(verdict="approve"), "operator")


async def test_work_is_listed_newest_first_and_filtered(stores: Stores) -> None:
    ticket = await stores.work.create(WorkKind.TICKET, {})
    stores.clock.advance(timedelta(seconds=1))
    alert = await stores.work.create(WorkKind.ALERT, {})
    stores.clock.advance(timedelta(seconds=1))
    await stores.work.set_status(ticket.id, WorkStatus.DONE)
    await stores.work.set_owner(alert.id, "ops")
    assert [item.id for item in await stores.work.list()] == [ticket.id, alert.id]
    assert [item.id for item in await stores.work.list(statuses={WorkStatus.NEW})] == [alert.id]
    assert [item.id for item in await stores.work.list(kinds={WorkKind.TICKET})] == [ticket.id]
    assert [item.id for item in await stores.work.list(owner="ops")] == [alert.id]
    assert len(await stores.work.list(limit=1)) == 1
    assert (await stores.work.get(alert.id)).owner == "ops"
