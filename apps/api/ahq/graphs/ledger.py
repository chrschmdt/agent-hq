from __future__ import annotations

from datetime import datetime
from typing import Any, NotRequired, TypedDict

from ahq.domain import AgentRun, CallReport, RunOutcome
from ahq.graphs.state import Disposition, TeamState


class Totals(TypedDict):
    version_id: str
    turns: int
    model_calls: int
    tool_calls: int
    input_tokens: int
    cached_tokens: NotRequired[int]
    output_tokens: int
    cost_usd: float
    seconds: float
    approvals: int
    rejected_approvals: int
    stop_reason: str | None
    started_at: str


def totals(state: TeamState, agent: str) -> Totals:
    entry: dict[str, Any] = dict(state.get("ledger", {})[agent])
    return Totals(**entry)


def opened(version_id: str, at: datetime) -> Totals:
    return Totals(
        version_id=version_id,
        turns=0,
        model_calls=0,
        tool_calls=0,
        input_tokens=0,
        cached_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        seconds=0.0,
        approvals=0,
        rejected_approvals=0,
        stop_reason=None,
        started_at=at.isoformat(),
    )


def charged(entry: Totals, report: CallReport | None, cost: float, seconds: float) -> Totals:
    usage = report.usage if report is not None else None
    return Totals(
        **{
            **entry,
            "model_calls": entry["model_calls"] + 1,
            "input_tokens": entry["input_tokens"]
            + (usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens if usage else 0),
            "cached_tokens": entry.get("cached_tokens", 0) + (usage.cache_read_tokens if usage else 0),
            "output_tokens": entry["output_tokens"] + (usage.output_tokens if usage else 0),
            "cost_usd": round(entry["cost_usd"] + cost, 8),
            "seconds": round(entry["seconds"] + seconds, 3),
        }
    )


def runs_of(state: TeamState, disposition: Disposition, at: datetime) -> list[AgentRun]:
    return [
        AgentRun(
            work_item_id=state["work_item_id"],
            agent=agent,
            version_id=entry["version_id"],
            kind=state["kind"],
            outcome=outcome_of(agent, state, disposition),
            turns=entry["turns"],
            model_calls=entry["model_calls"],
            tool_calls=entry["tool_calls"],
            input_tokens=entry["input_tokens"],
            cached_tokens=entry.get("cached_tokens", 0),
            output_tokens=entry["output_tokens"],
            cost_usd=entry["cost_usd"],
            seconds=entry["seconds"],
            approvals=entry["approvals"],
            rejected_approvals=entry["rejected_approvals"],
            stop_reason=entry["stop_reason"],
            started_at=datetime.fromisoformat(entry["started_at"]),
            updated_at=at,
        )
        for agent in state.get("ledger", {})
        for entry in [totals(state, agent)]
    ]


def outcome_of(agent: str, state: TeamState, disposition: Disposition) -> RunOutcome:
    if agent == "dispatcher":
        return "routed"
    passed_to = [handoff["to"] for handoff in state.get("handoffs", []) if handoff["from"] == agent]
    if passed_to:
        return "escalated" if passed_to[-1] == "human" else "handed_off"
    match disposition:
        case "waiting_customer":
            return "waiting_customer"
        case "escalated":
            return "escalated"
        case "done":
            return "resolved" if state["kind"] == "ticket" else "done"
