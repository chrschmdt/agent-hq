from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from ahq.domain import Event
from ahq.ports import EventLog

RECONNECT_MS = 1000
BATCH = 200


@dataclass(frozen=True)
class StreamLimits:
    max_seconds: float
    poll_seconds: float
    heartbeat_seconds: float


def format_event(event: Event) -> str:
    data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {event.id}\ndata: {data}\n\n"


async def event_stream(
    events: EventLog,
    *,
    after: int,
    limits: StreamLimits,
    monotonic: Callable[[], float],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AsyncIterator[str]:
    started = monotonic()
    last_sent = started
    cursor = after
    yield f"retry: {RECONNECT_MS}\n\n"
    while monotonic() - started < limits.max_seconds:
        batch = await events.read_after(cursor, limit=BATCH)
        for event in batch:
            cursor = event.id
            yield format_event(event)
        if batch:
            last_sent = monotonic()
        elif monotonic() - last_sent >= limits.heartbeat_seconds:
            last_sent = monotonic()
            yield ": heartbeat\n\n"
        if len(batch) < BATCH:
            await sleep(limits.poll_seconds)
