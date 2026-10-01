from __future__ import annotations

from dataclasses import dataclass

from ahq.domain import EvalJob, EvalRun
from ahq.ports import Queue


@dataclass(frozen=True)
class QueueLauncher:
    queue: Queue

    async def launch(self, run: EvalRun) -> None:
        await self.queue.send(EvalJob(eval_run_id=run.eval_run_id))
