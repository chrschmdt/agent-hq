from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, JsonValue

from ahq.domain import (
    EventKind,
    Incident,
    IncidentReport,
    ProposalRecord,
    ProposalSet,
    SupportTurn,
    incident_id_for,
    proposal_id_for,
)
from ahq.graphs.deps import TeamDeps
from ahq.graphs.state import TeamState, TeamUpdate

type Next = Literal["finalize", "insights", "human"]
AFTER_INCIDENT: dict[str, Next] = {"insights": "insights", "human": "human", "none": "finalize"}
type Emit = Callable[[EventKind, dict[str, JsonValue]], Awaitable[None]]


@dataclass(frozen=True)
class Conclusion:
    goto: Next
    update: TeamUpdate = field(default_factory=TeamUpdate)
    brief: str = ""


async def conclude(name: str, state: TeamState, answer: BaseModel, deps: TeamDeps, emit: Emit) -> Conclusion:
    outputs = {**state.get("outputs", {}), name: answer.model_dump(mode="json")}
    match answer:
        case SupportTurn():
            if answer.status == "transferred" or state.get("transferred"):
                return Conclusion("human", {"outputs": outputs}, brief=answer.summary)
            return Conclusion("finalize", {"outputs": outputs})
        case IncidentReport():
            incident_id = await _file_incident(state, answer, deps, emit)
            update: TeamUpdate = {"outputs": outputs, "incident_id": incident_id}
            return Conclusion(AFTER_INCIDENT[answer.next], update, _incident_brief(answer, incident_id))
        case ProposalSet():
            proposal_ids = await _file_proposals(state, answer, deps, emit)
            return Conclusion("finalize", {"outputs": outputs, "proposal_ids": proposal_ids})
        case _:
            raise TypeError(f"no outcome for {type(answer).__name__}")


async def _file_incident(state: TeamState, report: IncidentReport, deps: TeamDeps, emit: Emit) -> str | None:
    if deps.records is None:
        return None
    now = deps.clock.now()
    incident = await deps.records.file_incident(
        Incident(
            incident_id=incident_id_for(state["work_item_id"]),
            work_item_id=state["work_item_id"],
            report=report,
            status="open",
            detected_at=datetime.fromisoformat(state["now"]) if "now" in state else now,
            created_at=now,
        )
    )
    await emit(
        EventKind.INCIDENT_FILED,
        {
            "incident_id": incident.incident_id,
            "title": report.title,
            "severity": report.severity,
            "affected": report.affected.model_dump(mode="json"),
        },
    )
    return incident.incident_id


def _incident_brief(report: IncidentReport, incident_id: str | None) -> str:
    heading = f"Incident {incident_id}: {report.title}" if incident_id else f"Incident: {report.title}"
    return "\n\n".join(
        [
            f"{heading} (severity {report.severity})",
            report.brief or report.summary,
            f"Suspected cause: {report.suspected_cause}",
            f"Recommended action: {report.recommended_action}",
            "Evidence:\n" + "\n".join(f"- {item.query}: {item.excerpt}" for item in report.evidence),
        ]
    )


async def _file_proposals(state: TeamState, answer: ProposalSet, deps: TeamDeps, emit: Emit) -> list[str]:
    if deps.records is None:
        return []
    drafted = set(state.get("drafts", []))
    now = deps.clock.now()
    records = [
        ProposalRecord(
            proposal_id=proposal_id_for(state["work_item_id"], index),
            work_item_id=state["work_item_id"],
            incident_id=state.get("incident_id"),
            proposal=proposal if proposal.draft_id in drafted else proposal.model_copy(update={"draft_id": None}),
            status="pending",
            created_at=now,
        )
        for index, proposal in enumerate(answer.proposals)
    ]
    await deps.records.add_proposals(records)
    for record in records:
        await emit(
            EventKind.PROPOSAL_CREATED,
            {
                "proposal_id": record.proposal_id,
                "kind": record.proposal.kind,
                "title": record.proposal.title,
                "draft_id": record.proposal.draft_id,
                "incident_id": record.incident_id,
            },
        )
    return [record.proposal_id for record in records]
