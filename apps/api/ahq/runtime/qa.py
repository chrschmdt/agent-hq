from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from ahq.domain import QaReviewJob, ReviewRecord, WorkItemId
from ahq.grading import RunMaterial
from ahq.graphs import TeamState, run_material
from ahq.management import CanaryWatch, QualityDesk
from ahq.ports import WorkStore
from ahq.runtime.registry import GraphRegistry


@dataclass(frozen=True)
class QaReviews:
    work: WorkStore
    graphs: GraphRegistry
    quality: QualityDesk
    canary: CanaryWatch

    async def material(self, work_item_id: str, agent: str) -> RunMaterial:
        item = await self.work.get(WorkItemId(work_item_id))
        config: Any = {"configurable": {"thread_id": item.thread_id}}
        state = cast("TeamState", (await self.graphs.graph(item.kind).aget_state(config)).values)
        return run_material(state, agent)

    async def review(self, job: QaReviewJob) -> ReviewRecord | None:
        record = await self.quality.review(job, await self.material(job.work_item_id, job.agent))
        if record is not None and job.reason == "canary":
            await self.canary.check(job.agent)
        return record
