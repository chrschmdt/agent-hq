from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ahq.domain import Event, EventKind, WorkItemId
from ahq.graphs import run_path

START = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def events(*specs: tuple[EventKind, str, dict[str, object]]) -> list[Event]:
    return [
        Event.model_validate(
            {
                "id": n + 1,
                "kind": kind,
                "occurred_at": START + timedelta(seconds=n),
                "work_item_id": WorkItemId("wi_1"),
                "actor": actor,
                "payload": payload,
            }
        )
        for n, (kind, actor, payload) in enumerate(specs)
    ]


def test_an_alert_goes_through_the_dispatcher_ops_and_insights() -> None:
    path = run_path(
        events(
            (EventKind.WORK_CREATED, "monitor", {}),
            (EventKind.WORK_STARTED, "runtime", {}),
            (EventKind.MODEL_CALLED, "dispatcher", {"cost_usd": 0.001}),
            (EventKind.WORK_ROUTED, "dispatcher", {"route": "ops"}),
            (EventKind.MODEL_CALLED, "ops", {"cost_usd": 0.01}),
            (EventKind.TOOL_CALLED, "ops", {"tool": "analytics_run_sql"}),
            (EventKind.MODEL_CALLED, "ops", {"cost_usd": 0.02}),
            (EventKind.INCIDENT_FILED, "ops", {}),
            (EventKind.AGENT_HANDOFF, "ops", {"to": "insights"}),
            (EventKind.MODEL_CALLED, "insights", {"cost_usd": 0.005}),
            (EventKind.PROPOSAL_CREATED, "insights", {}),
            (EventKind.WORK_COMPLETED, "runtime", {}),
        )
    )
    assert [step.node for step in path] == ["dispatcher", "ops", "insights"]
    ops = path[1]
    assert (ops.model_calls, ops.tool_calls, round(ops.cost_usd, 3)) == (2, 1, 0.03)
    assert (ops.first_event_id, ops.last_event_id) == (5, 9)


def test_a_ticket_with_an_approval_ends_in_finalize() -> None:
    path = run_path(
        events(
            (EventKind.MODEL_CALLED, "support", {}),
            (EventKind.APPROVAL_REQUESTED, "runtime", {"approval_id": "apv_1"}),
            (EventKind.APPROVAL_DECIDED, "operator", {"approval_id": "apv_1"}),
            (EventKind.TOOL_CALLED, "support", {}),
            (EventKind.TICKET_REPLIED, "support", {}),
        )
    )
    assert [step.node for step in path] == ["support", "finalize"]
    assert path[0].waited_for_approval


def test_work_for_a_person_ends_in_human() -> None:
    routed = run_path(events((EventKind.WORK_ROUTED, "dispatcher", {"route": "human"})))
    assert [step.node for step in routed] == ["dispatcher", "human"]
    handed = run_path(events((EventKind.MODEL_CALLED, "ops", {}), (EventKind.AGENT_HANDOFF, "ops", {"to": "human"})))
    assert [step.node for step in handed] == ["ops", "human"]


def test_text_the_screen_blocks_goes_from_the_screen_to_a_person() -> None:
    path = run_path(
        events(
            (EventKind.WORK_STARTED, "runtime", {}),
            (EventKind.MODEL_CALLED, "guard", {"cost_usd": 0.0002}),
            (EventKind.GUARDRAIL_BLOCKED, "guard", {"stage": "input", "threat": "fraud"}),
            (EventKind.TICKET_REPLIED, "support", {}),
            (EventKind.WORK_ESCALATED, "runtime", {}),
        )
    )
    assert [step.node for step in path] == ["screen", "human", "finalize"]
    assert path[0].model_calls == 1
