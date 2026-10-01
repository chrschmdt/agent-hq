from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from ahq.api.deps import ContainerDep, Operator
from ahq.domain import Incident, KbDraft, NotFoundError, ProposalRecord, StrictModel

router = APIRouter(tags=["team"])

type ProposalStatus = Literal["pending", "approved", "rejected"]
type DraftStatus = Literal["pending", "published", "rejected"]


class ProposalDecision(StrictModel):
    verdict: Literal["approved", "rejected"]
    note: str | None = None


@router.get("/api/incidents")
async def list_incidents(container: ContainerDep, limit: int = Query(default=50, ge=1, le=200)) -> list[Incident]:
    return await container.records.incidents(limit)


@router.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str, container: ContainerDep) -> Incident:
    incident = await container.records.incident(incident_id)
    if incident is None:
        raise NotFoundError(f"incident {incident_id} not found")
    return incident


@router.get("/api/proposals")
async def list_proposals(container: ContainerDep, status: ProposalStatus | None = None) -> list[ProposalRecord]:
    return await container.records.proposals(status)


@router.get("/api/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, container: ContainerDep) -> ProposalRecord:
    proposal = await container.records.proposal(proposal_id)
    if proposal is None:
        raise NotFoundError(f"proposal {proposal_id} not found")
    return proposal


@router.post("/api/proposals/{proposal_id}/decision")
async def decide_proposal(
    proposal_id: str, decision: ProposalDecision, container: ContainerDep, operator: Operator
) -> ProposalRecord:
    return await container.desk.decide_proposal(proposal_id, decision.verdict, actor=operator, note=decision.note)


@router.get("/api/drafts")
async def list_drafts(container: ContainerDep, status: DraftStatus | None = None) -> list[KbDraft]:
    return await container.records.drafts(status)


@router.get("/api/drafts/{draft_id}")
async def get_draft(draft_id: str, container: ContainerDep) -> KbDraft:
    draft = await container.records.draft(draft_id)
    if draft is None:
        raise NotFoundError(f"draft {draft_id} not found")
    return draft
