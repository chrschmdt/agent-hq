from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from langchain_core.runnables import RunnableConfig
from pydantic import JsonValue


class TraceKind(StrEnum):
    ROUTINE = "routine"
    SMOKE = "smoke"
    EVAL = "eval"
    CANARY = "canary"
    SCENARIO = "scenario"


class Telemetry(Protocol):
    def run_config(
        self,
        *,
        run_id: str,
        run_name: str,
        kind: TraceKind,
        metadata: dict[str, JsonValue] | None = None,
    ) -> RunnableConfig: ...

    def is_traced(self, run_id: str, kind: TraceKind) -> bool: ...

    async def project_url(self) -> str | None: ...

    async def flush(self) -> None: ...
