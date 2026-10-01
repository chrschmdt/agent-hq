from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ahq.domain import (
    Affected,
    AgentRun,
    Incident,
    IncidentReport,
    WorkItem,
    WorkItemId,
    WorkKind,
    WorkStatus,
    thread_for,
)
from ahq.domain.world import Shipment, Ticket
from ahq.scorecards import team_value

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def item(n: int, status: WorkStatus, *, minutes: float = 0.0) -> WorkItem:
    work_item_id = WorkItemId(f"wi_{n}")
    return WorkItem(
        id=work_item_id,
        kind=WorkKind.TICKET,
        status=status,
        thread_id=thread_for(work_item_id),
        input={"ticket_id": f"tk_{n}"},
        created_at=NOW,
        updated_at=NOW + timedelta(minutes=minutes),
    )


def ticket(n: int, *, order_id: str | None = None, at: datetime = NOW) -> Ticket:
    return Ticket(
        ticket_id=f"tk_{n}",
        user_id=None,
        order_id=order_id,
        intent="where_is_my_order",
        subject="Where is my parcel?",
        status="open",
        source="simulation",
        created_at=at,
        messages=(),
    )


def run(n: int, cost: float, *, approvals: int = 0) -> AgentRun:
    return AgentRun(
        work_item_id=f"wi_{n}",
        agent="support",
        version_id="support@1",
        kind="ticket",
        outcome="resolved",
        turns=1,
        model_calls=2,
        tool_calls=1,
        input_tokens=100,
        output_tokens=20,
        cost_usd=cost,
        seconds=3.0,
        approvals=approvals,
        started_at=NOW,
        updated_at=NOW,
    )


def shipment(order_id: str, *, carrier: str = "northstar", delivered: bool = False) -> Shipment:
    return Shipment(
        tracking_id=f"tr_{order_id}",
        order_id=order_id,
        carrier=carrier,
        state="NY",
        region="northeast",
        status="delivered" if delivered else "in_transit",
        shipped_at=NOW - timedelta(days=2),
        delivered_at=NOW - timedelta(hours=1) if delivered else None,
    )


def incident() -> Incident:
    report = IncidentReport(
        title="Northstar parcels stuck in the Northeast",
        summary="Parcels are not moving.",
        evidence=[],
        suspected_cause="A hub outage.",
        affected=Affected(carrier="Northstar", region="Northeast", category=None, item_id=None, order_ids=[]),
        severity="high",
        recommended_action="Tell the customers.",
        next="none",
        brief="",
    )
    return Incident(
        incident_id="inc_1", work_item_id="wi_9", report=report, status="open", detected_at=NOW, created_at=NOW
    )


def test_resolved_tickets_are_priced_against_a_person_and_the_rest_counted_apart() -> None:
    items = [item(1, WorkStatus.DONE, minutes=4.0), item(2, WorkStatus.DONE, minutes=10.0)]
    items += [item(3, WorkStatus.ESCALATED, minutes=1.0), item(4, WorkStatus.WAITING_CUSTOMER)]
    runs = [run(1, 0.02), run(2, 0.04, approvals=1), run(3, 0.01), run(4, 0.01), run(99, 5.0)]
    value = team_value(items, runs, [], [], [], human_cost_per_ticket_usd=5.0)
    assert (value.tickets, value.resolved, value.with_people, value.open) == (4, 2, 1, 1)
    assert value.deflection_rate == pytest.approx(2 / 3)
    assert value.ticket_cost_usd == pytest.approx(0.08)
    assert value.cost_per_resolved_usd == pytest.approx(0.04)
    assert value.human_cost_usd == 10.0
    assert value.net_savings_usd == pytest.approx(9.92)
    assert value.median_minutes_to_resolve == 7.0
    assert value.approvals_per_100 == 25.0


def test_an_incident_reaches_the_delayed_customers_who_had_not_written_in() -> None:
    shipments = [
        shipment("#W1"),
        shipment("#W2"),
        shipment("#W3"),
        shipment("#W4", delivered=True),
        shipment("#W5", carrier="swiftline"),
    ]
    complaints = [
        ticket(1, order_id="#W1", at=NOW - timedelta(minutes=30)),
        ticket(2, order_id="#W2", at=NOW + timedelta(minutes=30)),
    ]
    value = team_value([], [], [incident()], shipments, complaints, human_cost_per_ticket_usd=5.0)
    assert (value.incidents, value.delayed_customers, value.reached_first) == (1, 3, 2)


def test_no_work_means_no_rates() -> None:
    value = team_value([], [], [], [], [], human_cost_per_ticket_usd=5.0)
    assert value.deflection_rate is None
    assert value.cost_per_resolved_usd is None
    assert value.approvals_per_100 is None
