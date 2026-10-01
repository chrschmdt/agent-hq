from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from ahq.api.deps import ContainerDep
from ahq.api.sse import StreamLimits, event_stream
from ahq.domain import Event, EventKind

router = APIRouter(tags=["events"])


@router.get("/api/events")
async def list_events(
    container: ContainerDep,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Event]:
    return await container.events.read_after(after, limit=limit)


@router.get("/api/events/recent")
async def recent_events(
    container: ContainerDep,
    kind: Annotated[list[EventKind] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Event]:
    return await container.events.recent(kinds=kind or None, limit=limit)


@router.get("/api/events/stream", response_class=StreamingResponse)
async def stream_events(
    container: ContainerDep,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    settings = container.settings
    if last_event_id and last_event_id.isdigit():
        cursor = int(last_event_id)
    elif after is not None:
        cursor = after
    else:
        cursor = await container.events.last_id()
    limits = StreamLimits(
        max_seconds=settings.sse_max_seconds,
        poll_seconds=settings.sse_poll_seconds,
        heartbeat_seconds=settings.sse_heartbeat_seconds,
    )
    stream = event_stream(container.events, after=cursor, limits=limits, monotonic=asyncio.get_running_loop().time)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
