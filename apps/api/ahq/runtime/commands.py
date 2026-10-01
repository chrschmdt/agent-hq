from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from pydantic import JsonValue

from ahq.domain import (
    Approval,
    ApprovalDecision,
    ApprovalId,
    ConflictError,
    EventKind,
    NewEvent,
    SegmentJob,
    WorkItem,
    WorkItemId,
    WorkKind,
    WorkStatus,
)
from ahq.domain.ids import new_ticket_id
from ahq.domain.world import Ticket, TicketMessage, TicketSource
from ahq.ports import ApprovalStore, Clock, EventLog, Queue, TicketLog, WorkStore


@dataclass(frozen=True)
class Commands:
    work: WorkStore
    approvals: ApprovalStore
    events: EventLog
    queue: Queue
    clock: Clock
    tickets: TicketLog

    async def submit_work(
        self, kind: WorkKind, input: dict[str, JsonValue], *, actor: str, key: str | None = None
    ) -> WorkItem:
        if key is not None and (existing := await self.work.by_key(key)) is not None:
            return existing
        item = await self.work.create(kind, input, key=key)
        await self._emit(EventKind.WORK_CREATED, item.id, actor, {"kind": kind.value})
        await self.queue.send(SegmentJob(action="start", work_item_id=item.id))
        return item

    async def open_ticket(
        self,
        messages: list[TicketMessage],
        *,
        actor: str,
        subject: str,
        source: TicketSource = "operator",
        today: date | None = None,
        brief: dict[str, JsonValue] | None = None,
        ticket_id: str | None = None,
        wait_for_customer: bool = False,
        owner: str | None = None,
    ) -> tuple[Ticket, WorkItem]:
        now = self.clock.now()
        ticket = Ticket(
            ticket_id=ticket_id or new_ticket_id(),
            user_id=None,
            intent="support",
            subject=subject,
            status="open",
            source=source,
            created_at=now,
            messages=tuple(messages),
        )
        await self.tickets.open_ticket(ticket)
        payload: dict[str, JsonValue] = {"ticket_id": ticket.ticket_id, "subject": subject, "source": source}
        await self._emit(EventKind.TICKET_OPENED, None, actor, payload)
        return ticket, await self.take_ticket(
            ticket.ticket_id,
            actor=actor,
            today=today or now.date(),
            brief=brief,
            wait_for_customer=wait_for_customer,
            owner=owner,
        )

    async def take_ticket(
        self,
        ticket_id: str,
        *,
        actor: str,
        today: date,
        brief: dict[str, JsonValue] | None = None,
        wait_for_customer: bool = False,
        owner: str | None = None,
        sim_run: str | None = None,
    ) -> WorkItem:
        work_input: dict[str, JsonValue] = {"ticket_id": ticket_id, "today": today.isoformat()}
        if brief is not None:
            work_input["brief"] = brief
        if owner is not None:
            work_input["owner"] = owner
        if sim_run is not None:
            work_input["sim_run"] = sim_run
        if not wait_for_customer:
            return await self.submit_work(WorkKind.TICKET, work_input, actor=actor)
        item = await self.work.create(WorkKind.TICKET, work_input)
        await self._emit(EventKind.WORK_CREATED, item.id, actor, {"kind": WorkKind.TICKET.value})
        waiting = await self.work.set_status(item.id, WorkStatus.WAITING_CUSTOMER)
        await self._emit(EventKind.WORK_WAITING_CUSTOMER, item.id, actor, {"outcome": None})
        return waiting

    async def customer_message(
        self, work_item_id: WorkItemId, text: str, *, actor: str, at: datetime | None = None
    ) -> int:
        item = await self.work.get(work_item_id)
        if item.kind is not WorkKind.TICKET:
            raise ConflictError(f"work item {item.id} is not a ticket")
        if item.status is not WorkStatus.WAITING_CUSTOMER:
            raise ConflictError(f"work item {item.id} is {item.status.value}, not waiting for the customer")
        ticket_id = str(item.input["ticket_id"])
        ticket = await self.tickets.ticket(ticket_id)
        if ticket is None:
            raise ConflictError(f"work item {item.id} points to a missing ticket")
        position = len(ticket.messages)
        message = TicketMessage(author="customer", body=text, created_at=at or self.clock.now())
        if not await self.tickets.add_message(ticket_id, position, message):
            raise ConflictError(f"ticket {ticket_id} already has a message at position {position}")
        await self._emit(
            EventKind.TICKET_MESSAGE, item.id, actor, {"ticket_id": ticket_id, "author": "customer", "body": text}
        )
        await self.queue.send(SegmentJob(action="customer_message", work_item_id=item.id, position=position))
        return position

    async def decide_approval(self, approval_id: ApprovalId, decision: ApprovalDecision, *, actor: str) -> Approval:
        approval = await self.approvals.decide(approval_id, decision, actor)
        payload: dict[str, JsonValue] = {"approval_id": approval.id, "verdict": decision.verdict}
        await self._emit(EventKind.APPROVAL_DECIDED, approval.work_item_id, actor, payload)
        await self.queue.send(SegmentJob(action="resume", work_item_id=approval.work_item_id, approval_id=approval.id))
        return approval

    async def cancel_work(self, work_item_id: WorkItemId, *, actor: str, reason: str) -> WorkItem:
        item = await self.work.get(work_item_id)
        if item.status.is_terminal:
            raise ConflictError(f"work item {item.id} is already {item.status.value}")
        item = await self.work.set_status(item.id, WorkStatus.CANCELLED, error=reason)
        await self._emit(EventKind.WORK_CANCELLED, item.id, actor, {"reason": reason})
        return item

    async def _emit(
        self, kind: EventKind, work_item_id: WorkItemId | None, actor: str, payload: dict[str, JsonValue]
    ) -> None:
        event = NewEvent(
            kind=kind, occurred_at=self.clock.now(), work_item_id=work_item_id, actor=actor, payload=payload
        )
        await self.events.append([event])
