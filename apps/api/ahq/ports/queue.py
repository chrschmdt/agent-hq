from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import Field

from ahq.domain import Job, StrictModel


class Delivery(StrictModel):
    attempt: int = Field(ge=1)


JobHandler = Callable[[Job, Delivery], Awaitable[None]]


class Queue(Protocol):
    async def send(self, job: Job, *, delay_seconds: float | None = None) -> None: ...
