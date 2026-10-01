from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue

from ahq.domain.agents import IncidentReport, Proposal
from ahq.domain.base import StrictModel
from ahq.domain.ids import WorkItemId

FLAG_TOOL = "flag_pattern"
FlagTopic = Literal["delivery", "product", "policy", "payments", "account", "other"]


class PatternFlag(StrictModel):
    topic: FlagTopic = Field(
        description="delivery for late, lost or damaged parcels; product for faults or confusion about a product; "
        "policy for rules customers misunderstand or dispute; payments, account, or other."
    )
    summary: str = Field(
        min_length=10,
        description="What customers report and why it looks like more than one case, in at most three sentences. "
        "Name the carrier, region, product or policy involved when you know it.",
    )
    ticket_ids: list[str] = Field(description="The tickets that show it, this one included.")


class KpiAlert(StrictModel):
    metric: str
    segment: dict[str, str] = Field(description="The dimension values the alert is about, such as carrier and region.")
    window_hours: int
    value: float
    baseline: float
    z_score: float
    ratio: float
    samples: int
    detected_at: AwareDatetime


def incident_id_for(work_item_id: WorkItemId | str) -> str:
    return f"inc_{work_item_id.removeprefix('wi_')}"


def proposal_id_for(work_item_id: WorkItemId | str, index: int) -> str:
    return f"prp_{work_item_id.removeprefix('wi_')}_{index}"


class Incident(StrictModel):
    incident_id: str
    work_item_id: str
    report: IncidentReport
    status: Literal["open", "closed"]
    detected_at: AwareDatetime
    created_at: AwareDatetime


class ProposalRecord(StrictModel):
    proposal_id: str
    work_item_id: str
    incident_id: str | None
    proposal: Proposal
    status: Literal["pending", "approved", "rejected"]
    decided_by: str | None = None
    note: str | None = None
    created_at: AwareDatetime
    decided_at: datetime | None = None


class KbDraft(StrictModel):
    draft_id: str
    doc_id: str
    version: int
    document: dict[str, JsonValue]
    status: Literal["pending", "published", "rejected"]
    created_at: AwareDatetime
    published_at: datetime | None = None
