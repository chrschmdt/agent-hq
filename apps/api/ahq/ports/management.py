from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import date, datetime, timedelta
from typing import Protocol

from pydantic import JsonValue

from ahq.domain import AgentControl, AgentRun, AgentVersion, ModelChoice, ModelHealth, Serving, SpendLine, VersionStatus


class VersionStore(Protocol):
    async def create(self, version: AgentVersion) -> AgentVersion: ...

    async def get(self, version_id: str) -> AgentVersion | None: ...

    async def list(self, agent: str | None = None) -> list[AgentVersion]: ...

    async def serving(self, agent: str) -> Serving: ...

    async def next_number(self, agent: str) -> int: ...

    async def set_status(
        self,
        version_id: str,
        status: VersionStatus,
        *,
        expected: Collection[VersionStatus],
        at: datetime,
        reason: str | None = None,
        canary_pct: int | None = None,
    ) -> AgentVersion: ...

    async def promote(
        self, version_id: str, *, expected: Collection[VersionStatus], at: datetime, reason: str
    ) -> tuple[AgentVersion, AgentVersion | None]: ...

    async def set_eval_summary(self, version_id: str, summary: dict[str, JsonValue]) -> AgentVersion: ...


class RunLedger(Protocol):
    async def record(self, runs: Sequence[AgentRun]) -> None: ...

    async def get(self, work_item_id: str, agent: str) -> AgentRun | None: ...

    async def runs(
        self,
        *,
        agent: str | None = None,
        version_id: str | None = None,
        finished: bool | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[AgentRun]: ...


class ControlStore(Protocol):
    async def controls(self) -> dict[str, AgentControl]: ...

    async def set_control(self, control: AgentControl) -> AgentControl: ...

    async def model_choice(self) -> ModelChoice | None: ...

    async def set_model_choice(self, choice: ModelChoice) -> ModelChoice: ...

    async def spend(self, day: date) -> list[SpendLine]: ...

    async def add_spend(self, day: date, agent: str, model: str, *, cost_usd: float, ok: bool) -> None: ...

    async def health(self) -> dict[str, ModelHealth]: ...

    async def record_call(
        self, model: str, *, ok: bool, at: datetime, errors_to_open: int, cooldown: timedelta, error: str | None = None
    ) -> tuple[ModelHealth, bool]: ...
