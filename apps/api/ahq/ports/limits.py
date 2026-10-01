from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ahq.domain import CallDecision


class Limits(Protocol):
    async def before_call(self, agent: str, model: str) -> CallDecision: ...

    async def after_call(
        self, agent: str, model: str, *, cost_usd: float, ok: bool, error: str | None = None
    ) -> None: ...

    async def paused(self) -> frozenset[str]: ...


class NoLimits:
    async def before_call(self, agent: str, model: str) -> CallDecision:
        return CallDecision(verdict="proceed", model=model)

    async def after_call(
        self, agent: str, model: str, *, cost_usd: float, ok: bool, error: str | None = None
    ) -> None: ...
    async def paused(self) -> frozenset[str]:
        return frozenset()


class Slots(Protocol):
    async def acquire(self, provider: str, holder: str, *, limit: int, now: datetime, until: datetime) -> bool: ...

    async def release(self, provider: str, holder: str) -> None: ...
