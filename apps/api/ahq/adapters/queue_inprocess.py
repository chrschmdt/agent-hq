from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
from dataclasses import dataclass, field

from ahq.domain import Job, RetryLater, Topic
from ahq.ports import Delivery, JobHandler

logger = logging.getLogger(__name__)
TOGETHER_SECONDS = 0.05


@dataclass(order=True)
class _Scheduled:
    due: float
    seq: int
    job: Job = field(compare=False)
    attempt: int = field(compare=False)


@dataclass(frozen=True)
class DeadLetter:
    job: Job
    attempts: int
    error: str


class InProcessQueue:
    def __init__(
        self,
        *,
        max_attempts: int = 5,
        retry_after_seconds: float = 2.0,
        duplicate_deliveries: bool = False,
    ) -> None:
        self._handlers: dict[Topic, JobHandler] = {}
        self._heap: list[_Scheduled] = []
        self._seq = itertools.count()
        self._seen_keys: set[str] = set()
        self._wakeup = asyncio.Event()
        self._virtual_now: float | None = None
        self._max_attempts = max_attempts
        self._retry_after = retry_after_seconds
        self._duplicate = duplicate_deliveries
        self.dead_letters: list[DeadLetter] = []

    def register(self, topic: Topic, handler: JobHandler) -> None:
        self._handlers[topic] = handler

    async def send(self, job: Job, *, delay_seconds: float | None = None) -> None:
        if job.idempotency_key in self._seen_keys:
            return
        self._seen_keys.add(job.idempotency_key)
        self._schedule(job, attempt=1, delay=delay_seconds or 0.0)
        if self._duplicate:
            self._schedule(job, attempt=1, delay=delay_seconds or 0.0)

    @property
    def pending(self) -> int:
        return len(self._heap)

    async def run_until_idle(
        self, *, virtual_time: bool = True, max_deliveries: int = 10_000, concurrency: int = 1
    ) -> int:
        self._virtual_now = 0.0 if virtual_time else None
        delivered = 0
        running: set[asyncio.Task[None]] = set()
        try:
            while (self._heap or running) and delivered < max_deliveries:
                while self._heap and len(running) < concurrency and delivered < max_deliveries:
                    wait = self._heap[0].due - self._now()
                    if wait > 0:
                        if running and wait > TOGETHER_SECONDS:
                            break
                        if virtual_time:
                            self._virtual_now = self._heap[0].due
                        else:
                            await asyncio.sleep(wait)
                    running.add(asyncio.create_task(self._deliver(heapq.heappop(self._heap))))
                    delivered += 1
                if running:
                    _, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            if running:
                await asyncio.wait(running)
        finally:
            self._virtual_now = None
        return delivered

    async def run_forever(self, stop: asyncio.Event, *, concurrency: int = 1) -> None:
        running: dict[Topic, set[asyncio.Task[None]]] = {}
        try:
            while not stop.is_set():
                now = self._now()
                held: list[_Scheduled] = []
                while self._heap and self._heap[0].due <= now:
                    item = heapq.heappop(self._heap)
                    lane = running.setdefault(item.job.topic, set())
                    if len(lane) < concurrency:
                        lane.add(asyncio.create_task(self._deliver(item)))
                    else:
                        held.append(item)
                for item in held:
                    heapq.heappush(self._heap, item)
                upcoming = [item.due for item in self._heap if item.due > now]
                wait = max(0.0, min(upcoming) - now) if upcoming else None
                self._wakeup.clear()
                in_flight = {task for lane in running.values() for task in lane}
                await self._wait(stop, wait_seconds=wait, running=in_flight)
                running = {topic: {task for task in lane if not task.done()} for topic, lane in running.items()}
        finally:
            in_flight = {task for lane in running.values() for task in lane}
            if in_flight:
                await asyncio.wait(in_flight)

    async def _wait(
        self, stop: asyncio.Event, wait_seconds: float | None, running: set[asyncio.Task[None]] | None = None
    ) -> None:
        helpers = {asyncio.ensure_future(self._wakeup.wait()), asyncio.ensure_future(stop.wait())}
        await asyncio.wait({*helpers, *(running or set())}, timeout=wait_seconds, return_when=asyncio.FIRST_COMPLETED)
        for helper in helpers:
            helper.cancel()

    async def _deliver(self, item: _Scheduled) -> None:
        handler = self._handlers.get(item.job.topic)
        if handler is None:
            self.dead_letters.append(DeadLetter(item.job, item.attempt, "no handler registered"))
            return
        try:
            await handler(item.job, Delivery(attempt=item.attempt))
        except RetryLater as retry:
            self._schedule(item.job, attempt=item.attempt + 1, delay=retry.after_seconds)
        except Exception as error:
            if item.attempt >= self._max_attempts:
                logger.exception("job %s failed after %d attempts", item.job.job_id, item.attempt)
                self.dead_letters.append(DeadLetter(item.job, item.attempt, repr(error)))
            else:
                logger.warning("job %s failed on attempt %d: %r", item.job.job_id, item.attempt, error)
                self._schedule(item.job, attempt=item.attempt + 1, delay=self._retry_after * item.attempt)

    def _schedule(self, job: Job, *, attempt: int, delay: float) -> None:
        heapq.heappush(self._heap, _Scheduled(self._now() + delay, next(self._seq), job, attempt))
        self._wakeup.set()

    def _now(self) -> float:
        if self._virtual_now is not None:
            return self._virtual_now
        return asyncio.get_running_loop().time()
