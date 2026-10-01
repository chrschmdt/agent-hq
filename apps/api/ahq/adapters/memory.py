from __future__ import annotations

import asyncio
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Literal

from pydantic import JsonValue

from ahq.domain import (
    Approval,
    ApprovalDecision,
    ApprovalId,
    ApprovalRequest,
    ApprovalStatus,
    ConflictError,
    Event,
    EventKind,
    NewEvent,
    NotFoundError,
    WorkItem,
    WorkItemId,
    WorkKind,
    WorkStatus,
    new_approval_id,
    new_work_item_id,
    thread_for,
)
from ahq.domain.recordings import RecordingInfo
from ahq.domain.retail import RetailSnapshot
from ahq.domain.sim import ScriptEntry, SimRun, SimStatus
from ahq.domain.team import Incident, KbDraft, ProposalRecord
from ahq.domain.world import (
    KpiDimension,
    KpiMetric,
    KpiPoint,
    Shipment,
    Ticket,
    TicketMessage,
    TicketStatus,
    WorldHistory,
)
from ahq.ports import Clock, RetailRepo


class MemoryEventLog:
    def __init__(self, clock: Clock | None = None) -> None:
        self._events: list[Event] = []
        self._cleared = 0
        self._lock = asyncio.Lock()
        self._clock = clock

    async def append(self, events: Sequence[NewEvent]) -> list[Event]:
        async with self._lock:
            recorded_at = self._clock.now() if self._clock is not None else None
            stored = [
                Event(id=self._cleared + len(self._events) + offset + 1, recorded_at=recorded_at, **event.model_dump())
                for offset, event in enumerate(events)
            ]
            self._events.extend(stored)
            return stored

    async def read_after(self, cursor: int, *, limit: int = 200) -> list[Event]:
        start = max(0, cursor - self._cleared)
        return self._events[start : start + limit]

    async def for_work_item(self, work_item_id: WorkItemId) -> list[Event]:
        return [event for event in self._events if event.work_item_id == work_item_id]

    async def recent(
        self, *, kinds: Collection[EventKind] | None = None, actor: str | None = None, limit: int = 50
    ) -> list[Event]:
        matching = [
            event
            for event in reversed(self._events)
            if (kinds is None or event.kind in kinds) and (actor is None or event.actor == actor)
        ]
        return matching[:limit]

    async def last_id(self) -> int:
        return self._cleared + len(self._events) if self._events else 0

    def clear_activity(self) -> dict[str, int]:
        count = len(self._events)
        self._cleared += count
        self._events = []
        return {"ops.events": count}


class MemoryWorkStore:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._items: dict[WorkItemId, WorkItem] = {}
        self._keys: dict[str, WorkItemId] = {}
        self._leases: dict[WorkItemId, tuple[str, datetime]] = {}
        self._lock = asyncio.Lock()

    async def create(self, kind: WorkKind, input: dict[str, JsonValue], *, key: str | None = None) -> WorkItem:
        if key is not None and key in self._keys:
            return self._items[self._keys[key]]
        now = self._clock.now()
        work_item_id = new_work_item_id()
        item = WorkItem(
            id=work_item_id,
            kind=kind,
            status=WorkStatus.NEW,
            thread_id=thread_for(work_item_id),
            input=input,
            created_at=now,
            updated_at=now,
        )
        self._items[item.id] = item
        if key is not None:
            self._keys[key] = item.id
        return item

    async def get(self, work_item_id: WorkItemId) -> WorkItem:
        try:
            return self._items[work_item_id]
        except KeyError:
            raise NotFoundError(f"work item {work_item_id} not found") from None

    async def by_key(self, key: str) -> WorkItem | None:
        work_item_id = self._keys.get(key)
        return self._items[work_item_id] if work_item_id is not None else None

    async def list(
        self,
        *,
        statuses: Collection[WorkStatus] | None = None,
        kinds: Collection[WorkKind] | None = None,
        owner: str | None = None,
        limit: int = 100,
    ) -> list[WorkItem]:
        matching = [
            item
            for item in self._items.values()
            if (statuses is None or item.status in statuses)
            and (kinds is None or item.kind in kinds)
            and (owner is None or item.owner == owner)
        ]
        return sorted(matching, key=lambda item: (item.updated_at, item.id), reverse=True)[:limit]

    async def set_owner(self, work_item_id: WorkItemId, owner: str) -> WorkItem:
        item = (await self.get(work_item_id)).model_copy(update={"owner": owner})
        self._items[item.id] = item
        return item

    async def set_status(self, work_item_id: WorkItemId, status: WorkStatus, *, error: str | None = None) -> WorkItem:
        item = await self.get(work_item_id)
        attempts = item.attempts + (1 if status is WorkStatus.RUNNING else 0)
        updated = item.model_copy(
            update={"status": status, "last_error": error, "attempts": attempts, "updated_at": self._clock.now()}
        )
        self._items[work_item_id] = updated
        return updated

    async def acquire_lease(self, work_item_id: WorkItemId, owner: str, ttl: timedelta) -> bool:
        async with self._lock:
            await self.get(work_item_id)
            now = self._clock.now()
            held = self._leases.get(work_item_id)
            if held and held[0] != owner and held[1] > now:
                return False
            self._leases[work_item_id] = (owner, now + ttl)
            return True

    async def release_lease(self, work_item_id: WorkItemId, owner: str) -> None:
        async with self._lock:
            held = self._leases.get(work_item_id)
            if held and held[0] == owner:
                del self._leases[work_item_id]

    async def count_active(self) -> int:
        return sum(item.status in {WorkStatus.NEW, WorkStatus.RUNNING} for item in self._items.values())

    def clear_activity(self) -> dict[str, int]:
        count = len(self._items)
        self._items, self._keys, self._leases = {}, {}, {}
        return {"ops.work_items": count}


class MemoryApprovalStore:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._approvals: dict[ApprovalId, Approval] = {}
        self._lock = asyncio.Lock()

    async def open(self, work_item_id: WorkItemId, interrupt_id: str, request: ApprovalRequest) -> Approval:
        async with self._lock:
            for approval in self._approvals.values():
                if approval.work_item_id == work_item_id and approval.interrupt_id == interrupt_id:
                    return approval
            approval = Approval(
                id=new_approval_id(),
                work_item_id=work_item_id,
                interrupt_id=interrupt_id,
                status=ApprovalStatus.PENDING,
                request=request,
                created_at=self._clock.now(),
            )
            self._approvals[approval.id] = approval
            return approval

    async def get(self, approval_id: ApprovalId) -> Approval:
        try:
            return self._approvals[approval_id]
        except KeyError:
            raise NotFoundError(f"approval {approval_id} not found") from None

    async def decide(self, approval_id: ApprovalId, decision: ApprovalDecision, decided_by: str) -> Approval:
        async with self._lock:
            approval = await self.get(approval_id)
            if approval.status is not ApprovalStatus.PENDING:
                raise ConflictError(f"approval {approval_id} was already decided")
            decided = approval.model_copy(
                update={
                    "status": decision.status,
                    "decision": decision,
                    "decided_by": decided_by,
                    "decided_at": self._clock.now(),
                }
            )
            self._approvals[approval_id] = decided
            return decided

    async def pending(self) -> list[Approval]:
        waiting = [a for a in self._approvals.values() if a.status is ApprovalStatus.PENDING]
        return sorted(waiting, key=lambda approval: approval.created_at)

    def clear_activity(self) -> dict[str, int]:
        count = len(self._approvals)
        self._approvals = {}
        return {"ops.approvals": count}


class MemoryWorldRepo:
    def __init__(self) -> None:
        self.history = WorldHistory(placed_at={}, shipments=(), refunds=())
        self._shipments: dict[str, Shipment] = {}
        self._tickets: dict[str, Ticket] = {}
        self.embeddings: dict[str, dict[str, list[float]]] = {"reviews": {}, "ticket_messages": {}}

    async def load(self, history: WorldHistory) -> None:
        self.history = history
        self._shipments = {shipment.tracking_id: shipment for shipment in history.shipments}
        self._tickets = {ticket.ticket_id: ticket for ticket in history.tickets}
        self.embeddings = {"reviews": {}, "ticket_messages": {}}

    async def shipments(self) -> list[Shipment]:
        return sorted(self._shipments.values(), key=lambda shipment: shipment.tracking_id)

    async def shipment(self, tracking_id: str) -> Shipment | None:
        return self._shipments.get(tracking_id)

    async def kpis(self, metric: KpiMetric, dimension: KpiDimension, *, days: int) -> list[KpiPoint]:
        points = [k for k in self.history.kpis if k.metric == metric and k.dimension == dimension]
        recent = sorted({point.day for point in points})[-days:]
        return sorted((p for p in points if p.day in recent), key=lambda p: (p.day, p.key))

    async def tickets_opened(self, since: datetime, until: datetime) -> list[Ticket]:
        opened = [t for t in self._tickets.values() if since < t.created_at <= until]
        return [
            t.model_copy(update={"messages": ()}) for t in sorted(opened, key=lambda t: (t.created_at, t.ticket_id))
        ]

    async def order_dates(self) -> dict[str, datetime]:
        return dict(self.history.placed_at)

    async def save_shipment(self, shipment: Shipment) -> bool:
        if self._shipments.get(shipment.tracking_id) == shipment:
            return False
        self._shipments[shipment.tracking_id] = shipment
        return True

    async def open_ticket(self, ticket: Ticket) -> bool:
        if ticket.ticket_id in self._tickets:
            return False
        self._tickets[ticket.ticket_id] = ticket
        return True

    async def ticket(self, ticket_id: str) -> Ticket | None:
        return self._tickets.get(ticket_id)

    async def add_message(self, ticket_id: str, position: int, message: TicketMessage) -> bool:
        ticket = self._tickets[ticket_id]
        if position < len(ticket.messages):
            return False
        if position > len(ticket.messages):
            raise ValueError(f"ticket {ticket_id} has no message at position {position - 1}")
        self._tickets[ticket_id] = ticket.model_copy(update={"messages": (*ticket.messages, message)})
        return True

    async def set_status(
        self, ticket_id: str, status: TicketStatus, *, resolved_at: datetime | None = None, csat: int | None = None
    ) -> None:
        ticket = self._tickets[ticket_id]
        update: dict[str, object] = {"status": status}
        if resolved_at is not None:
            update["resolved_at"] = resolved_at
        if csat is not None:
            update["csat"] = csat
        self._tickets[ticket_id] = ticket.model_copy(update=update)

    async def texts_to_embed(self, target: str, limit: int) -> list[tuple[str, str]]:
        if target == "reviews":
            texts = [(r.review_id, f"{r.title}\n{r.body}") for r in self.history.reviews]
        else:
            texts = [
                (f"{t.ticket_id}:{position}", message.body)
                for t in self._tickets.values()
                for position, message in enumerate(t.messages)
            ]
        return [(key, text) for key, text in texts if key not in self.embeddings[target]][:limit]

    async def save_embeddings(self, target: str, vectors: Mapping[str, Sequence[float]]) -> None:
        self.embeddings[target].update({key: list(vector) for key, vector in vectors.items()})

    def state(self) -> tuple[dict[str, Shipment], dict[str, Ticket]]:
        return dict(self._shipments), dict(self._tickets)

    def restore_state(self, state: tuple[dict[str, Shipment], dict[str, Ticket]]) -> None:
        self._shipments, self._tickets = dict(state[0]), dict(state[1])


class MemorySimStore:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._runs: dict[str, SimRun] = {}
        self._scripts: dict[str, list[ScriptEntry]] = {}

    async def create(self, run: SimRun, script: Sequence[ScriptEntry]) -> None:
        self._runs[run.run_id] = run
        self._scripts[run.run_id] = sorted(script, key=lambda entry: entry.seq)

    async def get(self, run_id: str) -> SimRun | None:
        return self._runs.get(run_id)

    async def latest(self) -> SimRun | None:
        return max(self._runs.values(), key=lambda run: run.created_at, default=None)

    async def runs(self, limit: int = 50) -> list[SimRun]:
        return sorted(self._runs.values(), key=lambda run: run.created_at, reverse=True)[:limit]

    async def due(self, run_id: str, *, after: datetime, until: datetime) -> list[ScriptEntry]:
        return [entry for entry in self._scripts[run_id] if after < entry.due_at <= until]

    async def advance(self, run_id: str, *, from_tick: int, sim_now: datetime, status: SimStatus) -> SimRun | None:
        run = self._runs[run_id]
        if run.tick_no != from_tick or run.status != "running":
            return None
        updated = run.model_copy(
            update={"tick_no": from_tick + 1, "sim_now": sim_now, "status": status, "updated_at": self._clock.now()}
        )
        self._runs[run_id] = updated
        return updated

    async def set_status(self, run_id: str, status: SimStatus) -> SimRun:
        run = self._runs.get(run_id)
        if run is None:
            raise NotFoundError(f"simulator run {run_id} not found")
        updated = run.model_copy(update={"status": status, "updated_at": self._clock.now()})
        self._runs[run_id] = updated
        return updated

    def clear_activity(self) -> dict[str, int]:
        counts = {"ops.sim_script": sum(map(len, self._scripts.values())), "ops.sim_runs": len(self._runs)}
        self._runs, self._scripts = {}, {}
        return counts


class MemoryBaseline:
    def __init__(self, retail: RetailRepo, world: MemoryWorldRepo) -> None:
        self._retail = retail
        self._world = world
        self._saved: tuple[RetailSnapshot, tuple[dict[str, Shipment], dict[str, Ticket]]] | None = None

    async def capture(self) -> None:
        self._saved = (await self._retail.snapshot(), self._world.state())

    async def restore(self) -> None:
        if self._saved is None:
            raise ConflictError("no baseline has been captured")
        snapshot, world = self._saved
        await self._retail.load(snapshot)
        self._world.restore_state(world)


class MemoryTeamRecords:
    def __init__(self) -> None:
        self._incidents: dict[str, Incident] = {}
        self._proposals: dict[str, ProposalRecord] = {}
        self._drafts: dict[str, KbDraft] = {}

    async def file_incident(self, incident: Incident) -> Incident:
        for existing in self._incidents.values():
            if existing.work_item_id == incident.work_item_id:
                return existing
        self._incidents[incident.incident_id] = incident
        return incident

    async def incident(self, incident_id: str) -> Incident | None:
        return self._incidents.get(incident_id)

    async def incidents(self, limit: int = 50) -> list[Incident]:
        return sorted(self._incidents.values(), key=lambda i: i.created_at, reverse=True)[:limit]

    async def add_proposals(self, proposals: Sequence[ProposalRecord]) -> None:
        for record in proposals:
            self._proposals.setdefault(record.proposal_id, record)

    async def proposal(self, proposal_id: str) -> ProposalRecord | None:
        return self._proposals.get(proposal_id)

    async def proposals(self, status: Literal["pending", "approved", "rejected"] | None = None) -> list[ProposalRecord]:
        chosen = [p for p in self._proposals.values() if status is None or p.status == status]
        return sorted(chosen, key=lambda p: (p.created_at, p.proposal_id), reverse=True)

    async def decide_proposal(
        self, proposal_id: str, status: Literal["approved", "rejected"], *, by: str, note: str | None, at: datetime
    ) -> ProposalRecord:
        record = self._proposals.get(proposal_id)
        if record is None:
            raise NotFoundError(f"proposal {proposal_id} not found")
        if record.status != "pending":
            raise ConflictError(f"proposal {proposal_id} was already {record.status}")
        decided = record.model_copy(update={"status": status, "decided_by": by, "note": note, "decided_at": at})
        self._proposals[proposal_id] = decided
        return decided

    async def save_draft(self, draft: KbDraft) -> KbDraft:
        return self._drafts.setdefault(draft.draft_id, draft)

    async def draft(self, draft_id: str) -> KbDraft | None:
        return self._drafts.get(draft_id)

    async def drafts(self, status: Literal["pending", "published", "rejected"] | None = None) -> list[KbDraft]:
        chosen = [d for d in self._drafts.values() if status is None or d.status == status]
        return sorted(chosen, key=lambda d: (d.created_at, d.draft_id))

    async def set_draft_status(
        self, draft_id: str, status: Literal["published", "rejected"], *, at: datetime
    ) -> KbDraft:
        draft = self._drafts.get(draft_id)
        if draft is None:
            raise NotFoundError(f"draft {draft_id} not found")
        updated = draft.model_copy(update={"status": status, "published_at": at if status == "published" else None})
        self._drafts[draft_id] = updated
        return updated

    def clear_activity(self) -> dict[str, int]:
        counts = {
            "agents.proposals": len(self._proposals),
            "agents.incidents": len(self._incidents),
            "agents.kb_drafts": len(self._drafts),
        }
        self._incidents, self._proposals, self._drafts = {}, {}, {}
        return counts


class MemoryRecordingStore:
    def __init__(self) -> None:
        self._recordings: dict[str, tuple[RecordingInfo, bytes]] = {}

    async def add(self, info: RecordingInfo, bundle: bytes) -> RecordingInfo:
        self._recordings[info.id] = (info, bundle)
        return info

    async def list(self, *, published_only: bool = False) -> list[RecordingInfo]:
        infos = [info for info, _ in self._recordings.values() if info.published or not published_only]
        return sorted(infos, key=lambda info: info.created_at, reverse=True)

    async def get(self, recording_id: str) -> RecordingInfo | None:
        found = self._recordings.get(recording_id)
        return found[0] if found else None

    async def bundle(self, recording_id: str) -> bytes | None:
        found = self._recordings.get(recording_id)
        return found[1] if found else None

    async def update(
        self, recording_id: str, *, published: bool | None = None, title: str | None = None
    ) -> RecordingInfo:
        found = self._recordings.get(recording_id)
        if found is None:
            raise NotFoundError(f"recording {recording_id} not found")
        info, bundle = found
        changes = {"published": published, "title": title}
        info = info.model_copy(update={key: value for key, value in changes.items() if value is not None})
        self._recordings[recording_id] = (info, bundle)
        return info

    async def delete(self, recording_id: str) -> None:
        self._recordings.pop(recording_id, None)
