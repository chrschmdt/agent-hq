from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, JsonValue

from ahq.domain.base import StrictModel
from ahq.domain.ids import WorkItemId


class EventKind(StrEnum):
    WORK_CREATED = "work.created"
    WORK_STARTED = "work.started"
    WORK_WAITING_APPROVAL = "work.waiting_approval"
    WORK_WAITING_CUSTOMER = "work.waiting_customer"
    WORK_DRAINED = "work.drained"
    WORK_DEFERRED = "work.deferred"
    WORK_COMPLETED = "work.completed"
    WORK_FAILED = "work.failed"
    WORK_ESCALATED = "work.escalated"
    WORK_CANCELLED = "work.cancelled"
    WORK_ROUTED = "work.routed"
    AGENT_HANDOFF = "agent.handoff"
    MODEL_CALLED = "model.called"
    TOOL_CALLED = "tool.called"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_DECIDED = "approval.decided"
    TICKET_OPENED = "ticket.opened"
    TICKET_MESSAGE = "ticket.message"
    TICKET_REPLIED = "ticket.replied"
    TICKET_CLOSED = "ticket.closed"
    TICKET_RATED = "ticket.rated"
    KPI_ALERT = "kpi.alert"
    PATTERN_FLAGGED = "pattern.flagged"
    INCIDENT_FILED = "incident.filed"
    PROPOSAL_CREATED = "proposal.created"
    PROPOSAL_DECIDED = "proposal.decided"
    KB_PUBLISHED = "kb.published"
    VERSION_CREATED = "version.created"
    VERSION_EVALUATED = "version.evaluated"
    VERSION_CANARY_STARTED = "version.canary_started"
    VERSION_PROMOTED = "version.promoted"
    VERSION_ROLLED_BACK = "version.rolled_back"
    VERSION_RETIRED = "version.retired"
    QA_REVIEWED = "qa.reviewed"
    EVAL_QUEUED = "eval.queued"
    EVAL_STARTED = "eval.started"
    EVAL_FINISHED = "eval.finished"
    MODELS_SWITCHED = "models.switched"
    ACTIVITY_CLEARED = "activity.cleared"
    AGENT_PAUSED = "agent.paused"
    AGENT_RESUMED = "agent.resumed"
    LIMIT_REACHED = "limit.reached"
    BREAKER_OPENED = "breaker.opened"
    GUARDRAIL_BLOCKED = "guardrail.blocked"
    ORDER_SHIPPED = "order.shipped"
    PARCEL_DELIVERED = "parcel.delivered"
    SIM_STARTED = "sim.started"
    SIM_PAUSED = "sim.paused"
    SIM_RESUMED = "sim.resumed"
    SIM_FINISHED = "sim.finished"
    SIM_STOPPED = "sim.stopped"


class NewEvent(StrictModel):
    kind: EventKind
    occurred_at: datetime
    work_item_id: WorkItemId | None = None
    actor: str | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class Event(NewEvent):
    id: int = Field(ge=1)
    recorded_at: datetime | None = None
