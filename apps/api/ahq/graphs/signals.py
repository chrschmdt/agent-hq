from __future__ import annotations

from typing import Any

from ahq.domain import KpiAlert, PatternFlag, WorkItem, WorkStatus
from ahq.graphs.tickets import WORK_STATUS


def alert_brief(alert: KpiAlert) -> str:
    segment = ", ".join(f"{key} {value}" for key, value in sorted(alert.segment.items()))
    return (
        f"KPI alert: {alert.metric} for {segment} was {alert.value:g} over the last {alert.window_hours} hours, "
        f"where {alert.baseline:g} was expected ({alert.ratio:g} times as high, z-score {alert.z_score:g}; "
        f"{alert.samples} in the window across all segments). Raised at {alert.detected_at.isoformat()}."
    )


def flag_brief(flag: PatternFlag, flagged_by: str, source: str) -> str:
    tickets = ", ".join(flag.ticket_ids) or "none given"
    return (
        f"Pattern flagged by {flagged_by} while working on {source}. Topic: {flag.topic}.\n\n{flag.summary}\n\n"
        f"Tickets: {tickets}"
    )


def alert_start(item: WorkItem) -> dict[str, Any]:
    alert = KpiAlert.model_validate(item.input["alert"])
    return {
        "work_item_id": item.id,
        "kind": "alert",
        "today": str(item.input["today"]),
        "now": alert.detected_at.isoformat(),
        "brief": alert_brief(alert),
    }


def flag_start(item: WorkItem) -> dict[str, Any]:
    flag = PatternFlag.model_validate(item.input["flag"])
    return {
        "work_item_id": item.id,
        "kind": "flag",
        "today": str(item.input["today"]),
        "now": str(item.input["raised_at"]),
        "brief": flag_brief(flag, str(item.input["flagged_by"]), str(item.input["source"])),
    }


def work_status(value: Any) -> WorkStatus:
    return WORK_STATUS[value["disposition"]]
