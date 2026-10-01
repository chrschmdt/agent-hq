from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory import MemoryEventLog
from ahq.adapters.memory_management import (
    MemoryControlStore,
    MemoryQualityStore,
    MemoryRunLedger,
    MemoryVersionStore,
)
from ahq.config import load_budget_config, load_canary_config, load_model_catalog, load_qa_config
from ahq.domain import AgentRun, Job, RunOutcome
from ahq.management import CanaryWatch, Limiter, QualityDesk, RunDesk, VersionRegistry
from ahq.testing import FakeChatModels

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@dataclass
class SentJobs:
    jobs: list[Job] = field(default_factory=list)

    async def send(self, job: Job, *, delay_seconds: float | None = None) -> None:
        self.jobs.append(job)


class Desk:
    def __init__(self) -> None:
        self.clock = ManualClock(NOW)
        self.events = MemoryEventLog()
        self.models = FakeChatModels()
        self.queue = SentJobs()
        self.ledger = MemoryRunLedger()
        self.controls = MemoryControlStore()
        catalog = load_model_catalog()
        self.registry = VersionRegistry(MemoryVersionStore(), self.events, self.clock, models=catalog.models.keys())
        self.limiter = Limiter(
            self.controls, self.events, self.clock, load_budget_config(), lambda m: catalog.models[m].fallback
        )
        self.quality = QualityDesk(
            self.models, MemoryQualityStore(), self.limiter, self.events, self.clock, load_qa_config()
        )
        self.canary = CanaryWatch(self.registry, self.ledger, self.quality, load_canary_config())
        self.runs = RunDesk(
            self.ledger,
            self.queue,
            self.registry,
            self.canary,
            self.limiter,
            self.clock,
            qa=load_qa_config(),
            budgets=load_budget_config(),
        )

    async def kinds(self) -> list[str]:
        return [event.kind.value for event in await self.events.read_after(0, limit=10_000)]


def agent_run(
    work_item_id: str, version_id: str = "support@1", outcome: RunOutcome = "resolved", *, rejected: int = 0
) -> AgentRun:
    return AgentRun(
        work_item_id=work_item_id,
        agent=version_id.partition("@")[0],
        version_id=version_id,
        kind="ticket",
        outcome=outcome,
        turns=1,
        model_calls=2,
        tool_calls=1,
        input_tokens=500,
        output_tokens=50,
        cost_usd=0.01,
        seconds=3.0,
        approvals=rejected,
        rejected_approvals=rejected,
        started_at=NOW,
        updated_at=NOW,
    )
