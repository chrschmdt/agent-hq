from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from uuid import uuid4

import httpx
import httpx2

from ahq.config import CallPolicy
from ahq.domain import RetryLater
from ahq.ports import Clock, Slots

RETRYABLE = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})
SLOT_POLL_SECONDS = 0.5


class Governor:
    def __init__(
        self,
        provider: str,
        policy: CallPolicy,
        clock: Clock,
        *,
        slots: Slots | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.provider = provider
        self._policy = policy
        self._clock = clock
        self._slots = slots
        self._sleep = sleep
        self._jitter = jitter

    async def send(self, send: Callable[[], Awaitable[Any]]) -> Any:
        policy = self._policy
        for attempt in range(policy.attempts):
            async with self._slot():
                response = await send()
            if response.status_code not in RETRYABLE:
                return response
            wait = self.wait(attempt, retry_after(response.headers, self._clock.now()))
            reason = f"{self.provider} answered {response.status_code}"
            if attempt == policy.attempts - 1 or wait > policy.max_wait_seconds:
                raise RetryLater(max(wait, policy.backoff_seconds), reason)
            await self._sleep(wait)
        raise AssertionError("every attempt returns or raises")

    def wait(self, attempt: int, asked: float | None) -> float:
        ceiling = min(self._policy.max_wait_seconds, self._policy.backoff_seconds * 2**attempt)
        return max(self._jitter() * ceiling, asked or 0.0)

    @asynccontextmanager
    async def _slot(self) -> AsyncIterator[None]:
        if self._slots is None:
            yield
            return
        holder = uuid4().hex
        limit = self._policy.slots_for(self.provider)
        waited = 0.0
        while not await self._slots.acquire(
            self.provider,
            holder,
            limit=limit,
            now=self._clock.now(),
            until=self._clock.now() + timedelta(seconds=self._policy.lease_seconds),
        ):
            if waited >= self._policy.wait_seconds:
                reason = f"all {limit} {self.provider} slots stayed busy for {waited:.0f}s"
                raise RetryLater(self._policy.backoff_seconds * (1 + self._jitter()) * 4, reason)
            pause = SLOT_POLL_SECONDS * (1 + self._jitter())
            await self._sleep(pause)
            waited += pause
        try:
            yield
        finally:
            await self._slots.release(self.provider, holder)


class GovernedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, governor: Governor, inner: httpx2.AsyncBaseTransport | None = None) -> None:
        self.governor = governor
        self._inner = inner or httpx2.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        async def send() -> httpx2.Response:
            response = await self._inner.handle_async_request(request)
            await response.aread()
            return response

        response: httpx2.Response = await self.governor.send(send)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class GovernedHttpxTransport(httpx.AsyncBaseTransport):
    def __init__(self, governor: Governor, inner: httpx.AsyncBaseTransport | None = None) -> None:
        self.governor = governor
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        async def send() -> httpx.Response:
            response = await self._inner.handle_async_request(request)
            await response.aread()
            return response

        response: httpx.Response = await self.governor.send(send)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


def retry_after(headers: httpx.Headers | httpx2.Headers, now: datetime) -> float | None:
    if (millis := headers.get("retry-after-ms")) is not None:
        try:
            return max(float(millis) / 1000, 0.0)
        except ValueError:
            return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        pass
    try:
        return max((parsedate_to_datetime(value) - now).total_seconds(), 0.0)
    except (TypeError, ValueError):
        return None


def provider_of(model_id: str) -> str:
    return model_id.split("/", 1)[0]
