from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from ahq.domain import NotFoundError, WorkItem, WorkStatus
from ahq.domain.world import Ticket, TicketMessage
from ahq.ports import TicketLog

CUSTOMER_MESSAGE = re.compile(r"#\d+$")
WORK_STATUS = {
    "waiting_customer": WorkStatus.WAITING_CUSTOMER,
    "done": WorkStatus.DONE,
    "escalated": WorkStatus.ESCALATED,
}


def message_id(ticket_id: str, position: int) -> str:
    return f"{ticket_id}#{position}"


def as_thread_message(ticket_id: str, position: int, message: TicketMessage) -> AnyMessage:
    if message.author == "agent":
        return AIMessage(message.body, id=message_id(ticket_id, position))
    return HumanMessage(message.body, id=message_id(ticket_id, position))


def customer_messages(messages: Sequence[AnyMessage]) -> list[HumanMessage]:
    return [m for m in messages if isinstance(m, HumanMessage) and CUSTOMER_MESSAGE.search(m.id or "") is not None]


def ticket_start(tickets: TicketLog) -> Callable[[WorkItem], Awaitable[dict[str, Any]]]:
    async def start(item: WorkItem) -> dict[str, Any]:
        ticket = await _ticket(tickets, item)
        opening = next((message.body for message in ticket.messages if message.author == "customer"), "")
        return {
            "work_item_id": item.id,
            "kind": "ticket",
            "ticket_id": ticket.ticket_id,
            "today": str(item.input["today"]),
            "brief": f"Subject: {ticket.subject}\n\n{opening}",
            "owner": item.input.get("owner"),
            "reply_position": len(ticket.messages),
            "support_messages": [
                as_thread_message(ticket.ticket_id, position, message)
                for position, message in enumerate(ticket.messages)
            ],
        }

    return start


def ticket_message(tickets: TicketLog) -> Callable[[WorkItem, int], Awaitable[dict[str, Any]]]:
    async def next_turn(item: WorkItem, position: int) -> dict[str, Any]:
        ticket = await _ticket(tickets, item)
        if position >= len(ticket.messages):
            raise NotFoundError(f"ticket {ticket.ticket_id} has no message at position {position}")
        message = as_thread_message(ticket.ticket_id, position, ticket.messages[position])
        return {"support_messages": [message], "reply_position": position + 1}

    return next_turn


def ticket_status(value: Any) -> WorkStatus:
    return WORK_STATUS[value["disposition"]]


async def _ticket(tickets: TicketLog, item: WorkItem) -> Ticket:
    ticket = await tickets.ticket(str(item.input["ticket_id"]))
    if ticket is None:
        raise NotFoundError(f"work item {item.id} points to a missing ticket")
    return ticket
