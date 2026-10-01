from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ahq.domain import NotFoundError, WorkItemId
from ahq.ports import Clock, SimStore, WorkStore


@dataclass(frozen=True)
class StoreTime:
    work: WorkStore
    runs: SimStore
    clock: Clock

    async def simulated(self, work_item_id: str) -> datetime | None:
        try:
            item = await self.work.get(WorkItemId(work_item_id))
        except NotFoundError:
            return None
        run_id = item.input.get("sim_run")
        if not isinstance(run_id, str):
            return None
        run = await self.runs.get(run_id)
        return run.sim_now if run is not None else None

    async def now(self, work_item_id: str) -> datetime:
        return await self.simulated(work_item_id) or self.clock.now()
