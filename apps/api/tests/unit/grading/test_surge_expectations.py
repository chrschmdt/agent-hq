from __future__ import annotations

from datetime import UTC, datetime

from ahq.domain import WorkItem, WorkItemId, WorkKind, WorkStatus, thread_for
from ahq.grading import every_customer_answered, within_budget, within_slots

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def item(n: int, status: WorkStatus) -> WorkItem:
    work_item_id = WorkItemId(f"wi_{n}")
    return WorkItem(
        id=work_item_id,
        kind=WorkKind.TICKET,
        status=status,
        thread_id=thread_for(work_item_id),
        created_at=NOW,
        updated_at=NOW,
    )


def test_work_that_finished_went_to_a_person_or_waits_counts_as_answered() -> None:
    settled = [
        item(1, WorkStatus.DONE),
        item(2, WorkStatus.ESCALATED),
        item(3, WorkStatus.WAITING_CUSTOMER),
        item(4, WorkStatus.WAITING_APPROVAL),
    ]
    result = every_customer_answered(settled, dead_letters=0, deferred=3)
    assert result.met
    assert result.detail == "4 of 4 answered, 3 deferrals, 0 dropped"


def test_failed_or_unfinished_work_or_a_dropped_job_fails_the_surge() -> None:
    failed = every_customer_answered([item(1, WorkStatus.DONE), item(2, WorkStatus.FAILED)], dead_letters=0, deferred=0)
    assert not failed.met
    assert failed.detail.endswith("unanswered: failed")
    assert not every_customer_answered([item(1, WorkStatus.RUNNING)], dead_letters=0, deferred=0).met
    assert not every_customer_answered([item(1, WorkStatus.DONE)], dead_letters=1, deferred=0).met
    assert not every_customer_answered([], dead_letters=0, deferred=0).met


def test_calls_in_flight_are_checked_against_each_providers_slots() -> None:
    held = within_slots({"openai": 8, "voyageai": 3}, {"openai": 8, "voyageai": 4})
    assert held.met
    assert held.detail == "openai: at most 8 of 8, voyageai: at most 3 of 4"
    assert not within_slots({"openai": 9}, {"openai": 8}).met


def test_spend_is_checked_against_the_daily_budget() -> None:
    assert within_budget(4.99, 5.0).met
    assert not within_budget(5.01, 5.0).met
