from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ahq.domain.world import Ticket, TicketMessage, TicketStatus


class TicketLog(Protocol):
    async def open_ticket(self, ticket: Ticket) -> bool: ...

    async def ticket(self, ticket_id: str) -> Ticket | None: ...

    async def add_message(self, ticket_id: str, position: int, message: TicketMessage) -> bool: ...

    async def set_status(
        self, ticket_id: str, status: TicketStatus, *, resolved_at: datetime | None = None, csat: int | None = None
    ) -> None: ...
