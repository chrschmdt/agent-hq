from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import Field

from ahq.api.deps import ContainerDep, Operator
from ahq.domain import NotFoundError, StrictModel, WorkItem, WorkItemId
from ahq.domain.world import Ticket, TicketMessage

router = APIRouter(tags=["tickets"])


class OpenTicket(StrictModel):
    message: str = Field(min_length=1, max_length=4000)
    subject: str | None = Field(default=None, max_length=200)


class TicketOpened(StrictModel):
    ticket: Ticket
    work_item: WorkItem


class CustomerMessage(StrictModel):
    text: str = Field(min_length=1, max_length=4000)


class MessageAccepted(StrictModel):
    position: int


@router.post("/api/tickets", status_code=status.HTTP_201_CREATED)
async def open_ticket(body: OpenTicket, container: ContainerDep, operator: Operator) -> TicketOpened:
    message = TicketMessage(author="customer", body=body.message, created_at=container.clock.now())
    subject = body.subject or body.message[:80]
    ticket, item = await container.commands.open_ticket([message], actor=operator, subject=subject)
    return TicketOpened(ticket=ticket, work_item=item)


@router.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, container: ContainerDep) -> Ticket:
    ticket = await container.tickets.ticket(ticket_id)
    if ticket is None:
        raise NotFoundError(f"ticket {ticket_id} not found")
    return ticket


@router.post("/api/work/{work_item_id}/messages", status_code=status.HTTP_202_ACCEPTED)
async def customer_message(
    work_item_id: WorkItemId, body: CustomerMessage, container: ContainerDep, operator: Operator
) -> MessageAccepted:
    position = await container.commands.customer_message(work_item_id, body.text, actor=operator)
    return MessageAccepted(position=position)
