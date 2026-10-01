from __future__ import annotations

import json

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory import MemoryEventLog
from ahq.api.sse import StreamLimits, event_stream, format_event
from ahq.domain import Event, EventKind, NewEvent


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def new_event(kind: EventKind = EventKind.WORK_CREATED) -> NewEvent:
    return NewEvent(kind=kind, occurred_at=ManualClock().now(), payload={"n": 1})


async def collect(log: MemoryEventLog, *, after: int, limits: StreamLimits) -> list[str]:
    time = FakeTime()
    return [
        message
        async for message in event_stream(log, after=after, limits=limits, monotonic=time.monotonic, sleep=time.sleep)
    ]


async def test_streams_events_after_the_cursor_with_their_ids() -> None:
    log = MemoryEventLog()
    await log.append([new_event(), new_event(EventKind.WORK_STARTED), new_event(EventKind.WORK_COMPLETED)])
    messages = await collect(log, after=1, limits=StreamLimits(max_seconds=1, poll_seconds=0.5, heartbeat_seconds=10))
    events = [message for message in messages if message.startswith("id:")]
    assert [message.splitlines()[0] for message in events] == ["id: 2", "id: 3"]
    assert json.loads(events[0].splitlines()[1].removeprefix("data: "))["kind"] == "work.started"


async def test_tells_the_browser_how_fast_to_reconnect() -> None:
    messages = await collect(
        MemoryEventLog(), after=0, limits=StreamLimits(max_seconds=1, poll_seconds=0.5, heartbeat_seconds=10)
    )
    assert messages[0] == "retry: 1000\n\n"


async def test_sends_heartbeats_while_idle_and_closes_at_the_limit() -> None:
    messages = await collect(
        MemoryEventLog(), after=0, limits=StreamLimits(max_seconds=60, poll_seconds=1, heartbeat_seconds=15)
    )
    assert messages.count(": heartbeat\n\n") == 3


def test_format_event_is_one_complete_sse_message() -> None:
    event = Event(id=7, **new_event().model_dump())
    lines = format_event(event).split("\n")
    assert lines[0] == "id: 7"
    data = json.loads(lines[1].removeprefix("data: "))
    assert (data["kind"], data["payload"]) == ("work.created", {"n": 1})
    assert lines[2:] == ["", ""]
