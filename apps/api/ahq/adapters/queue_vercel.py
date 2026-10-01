from __future__ import annotations

from datetime import timedelta

from vercel.queue import QueueClient

from ahq.domain import Job


class VercelQueue:
    def __init__(self, *, region: str) -> None:
        self._client = QueueClient(region=region)

    async def send(self, job: Job, *, delay_seconds: float | None = None) -> None:
        await self._client.send(
            str(job.topic),
            job.model_dump(mode="json"),
            idempotency_key=job.idempotency_key,
            delay=timedelta(seconds=delay_seconds) if delay_seconds else None,
        )
