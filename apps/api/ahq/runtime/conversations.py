from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pydantic import JsonValue

from ahq.domain import (
    CallReport,
    CustomerTurnJob,
    EventKind,
    NewEvent,
    SegmentJob,
    WorkItem,
    WorkItemId,
    WorkStatus,
)
from ahq.domain.sim import CustomerBrief
from ahq.domain.world import Ticket, TicketMessage, TicketStatus
from ahq.ports import ChatModels, Clock, EventLog, Queue, TicketLog, WorkStore
from ahq.runtime.commands import Commands
from ahq.runtime.store_time import StoreTime
from ahq.sim.customer import CustomerSimulator, Ending, brief_scenario

ACTOR = "customer"
MAX_CUSTOMER_TURNS = 25
CLOSING: dict[Ending | None, tuple[WorkStatus, TicketStatus]] = {
    "stop": (WorkStatus.DONE, "resolved"),
    "out_of_scope": (WorkStatus.DONE, "resolved"),
    "transfer": (WorkStatus.ESCALATED, "escalated"),
    None: (WorkStatus.ESCALATED, "escalated"),
}

FINISHED = {WorkStatus.DONE: EventKind.WORK_COMPLETED, WorkStatus.ESCALATED: EventKind.WORK_ESCALATED}


@dataclass(frozen=True)
class Conversations:
    work: WorkStore
    tickets: TicketLog
    commands: Commands
    events: EventLog
    queue: Queue
    clock: Clock
    models: ChatModels
    customer: CustomerSimulator
    typing_seconds: float = 4.0
    store_time: StoreTime | None = None

    async def take(self, ticket: Ticket, brief: CustomerBrief, *, run_id: str, today: date) -> None:
        scenario = brief_scenario(brief)
        await self.commands.take_ticket(
            ticket.ticket_id,
            actor="simulator",
            today=today,
            brief={"scenario": scenario, "brief_id": brief.brief_id},
            sim_run=run_id,
        )

    async def after_reply(self, work_item_id: str, reply_position: int, waiting_for_customer: bool) -> None:
        item = await self.work.get(WorkItemId(work_item_id))
        if "brief" not in item.input:
            return
        job = CustomerTurnJob(work_item_id=item.id, position=reply_position + 1, rate_only=not waiting_for_customer)
        await self.queue.send(job, delay_seconds=self.typing_seconds)

    async def turn(self, job: CustomerTurnJob) -> None:
        item = await self.work.get(job.work_item_id)
        instructions = _scenario(item)
        ticket = await self.tickets.ticket(str(item.input["ticket_id"]))
        if instructions is None or ticket is None:
            return
        if job.rate_only:
            await self._rate(item, ticket, instructions)
            return
        if item.status is not WorkStatus.WAITING_CUSTOMER:
            return
        if job.position < len(ticket.messages):
            if ticket.messages[job.position].author == "customer":
                await self.queue.send(
                    SegmentJob(action="customer_message", work_item_id=item.id, position=job.position)
                )
            return
        if sum(m.author == "customer" for m in ticket.messages) >= MAX_CUSTOMER_TURNS:
            await self._close(item, ticket, None, instructions)
            return
        started = self.clock.now()
        turn, report = await self.customer.next_turn(instructions, ticket.messages)
        await self._record(item, report, (self.clock.now() - started).total_seconds())
        if turn.ending is None:
            said_at = await self.store_time.now(item.id) if self.store_time is not None else None
            await self.commands.customer_message(item.id, turn.text, actor=ACTOR, at=said_at)
            return
        if turn.text:
            said_at = await self.store_time.now(item.id) if self.store_time is not None else self.clock.now()
            message = TicketMessage(author="customer", body=turn.text, created_at=said_at)
            await self.tickets.add_message(ticket.ticket_id, len(ticket.messages), message)
            ticket = await self.tickets.ticket(ticket.ticket_id) or ticket
        await self._close(item, ticket, turn.ending, instructions)

    async def _close(self, item: WorkItem, ticket: Ticket, ending: Ending | None, instructions: str) -> None:
        status, ticket_status = CLOSING[ending]
        ended_at = await self.store_time.now(item.id) if self.store_time is not None else self.clock.now()
        await self.tickets.set_status(ticket.ticket_id, ticket_status, resolved_at=ended_at)
        await self.work.set_status(item.id, status)
        outcome = ending or "max_turns"
        await self._emit(item, FINISHED[status], {"outcome": outcome})
        payload: dict[str, JsonValue] = {"ticket_id": ticket.ticket_id, "outcome": outcome}
        await self._emit(item, EventKind.TICKET_CLOSED, payload)
        await self._rate(item, ticket, instructions)

    async def _rate(self, item: WorkItem, ticket: Ticket, instructions: str) -> None:
        started = self.clock.now()
        rating, report = await self.customer.rate(instructions, ticket.messages)
        await self._record(item, report, (self.clock.now() - started).total_seconds())
        current = await self.tickets.ticket(ticket.ticket_id) or ticket
        await self.tickets.set_status(ticket.ticket_id, current.status, csat=rating.score)
        await self._emit(
            item, EventKind.TICKET_RATED, {"ticket_id": ticket.ticket_id, "csat": rating.score, "reason": rating.reason}
        )

    async def _record(self, item: WorkItem, report: CallReport, seconds: float) -> None:
        payload: dict[str, JsonValue] = {
            "agent": ACTOR,
            "model": self.models.model_key("customer"),
            "provider": report.provider,
            "usage": report.usage.model_dump(),
            "cost_usd": report.cost_usd(self.models.price("customer")),
            "seconds": round(seconds, 3),
        }
        await self._emit(item, EventKind.MODEL_CALLED, payload)

    async def _emit(self, item: WorkItem, kind: EventKind, payload: dict[str, JsonValue]) -> None:
        event = NewEvent(kind=kind, occurred_at=self.clock.now(), work_item_id=item.id, actor=ACTOR, payload=payload)
        await self.events.append([event])


def _scenario(item: WorkItem) -> str | None:
    brief = item.input.get("brief")
    if not isinstance(brief, dict):
        return None
    scenario = brief.get("scenario")
    return scenario if isinstance(scenario, str) else None
