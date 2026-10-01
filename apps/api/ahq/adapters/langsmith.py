from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable

from langchain_core.runnables import RunnableConfig
from langchain_core.tracers.langchain import LangChainTracer, wait_for_all_tracers
from langsmith import Client
from langsmith.anonymizer import create_anonymizer
from pydantic import JsonValue, SecretStr

from ahq.ports import TraceKind

ALWAYS_TRACED = frozenset({TraceKind.SMOKE, TraceKind.EVAL, TraceKind.CANARY, TraceKind.SCENARIO})
WEB_URL = "https://smith.langchain.com"


def sampled(run_id: str, rate: float) -> bool:
    digest = hashlib.sha256(run_id.encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < rate


class LangSmithTelemetry:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        project: str,
        sample_rate: float,
        redact: Callable[[str], str] | None = None,
    ) -> None:
        anonymizer = create_anonymizer(lambda text, _path: redact(text)) if redact is not None else None
        self._client = Client(api_key=api_key.get_secret_value(), anonymizer=anonymizer)
        self._project = project
        self._rate = sample_rate
        self._project_url: str | None = None

    def is_traced(self, run_id: str, kind: TraceKind) -> bool:
        return kind in ALWAYS_TRACED or sampled(run_id, self._rate)

    def run_config(
        self,
        *,
        run_id: str,
        run_name: str,
        kind: TraceKind,
        metadata: dict[str, JsonValue] | None = None,
    ) -> RunnableConfig:
        config = RunnableConfig(
            run_name=run_name, tags=[kind.value], metadata={"ahq_run_id": run_id, **(metadata or {})}
        )
        if self.is_traced(run_id, kind):
            config["callbacks"] = [LangChainTracer(project_name=self._project, client=self._client)]
        return config

    async def project_url(self) -> str | None:
        if self._project_url is None:
            try:
                project = await asyncio.to_thread(self._client.read_project, project_name=self._project)
            except Exception:
                return None
            self._project_url = f"{WEB_URL}/o/{project.tenant_id}/projects/p/{project.id}"
        return self._project_url

    async def flush(self) -> None:
        await asyncio.to_thread(wait_for_all_tracers)
        await asyncio.to_thread(self._client.flush)


class NoopTelemetry:
    def is_traced(self, run_id: str, kind: TraceKind) -> bool:
        return False

    def run_config(
        self,
        *,
        run_id: str,
        run_name: str,
        kind: TraceKind,
        metadata: dict[str, JsonValue] | None = None,
    ) -> RunnableConfig:
        return RunnableConfig(run_name=run_name, tags=[kind.value], metadata={"ahq_run_id": run_id, **(metadata or {})})

    async def project_url(self) -> str | None:
        return None

    async def flush(self) -> None: ...
