from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ahq.domain import CustomerTurnJob, Job, NotFoundError, QaReviewJob, SegmentJob, SimTickJob, Topic, deferral
from ahq.ports import Delivery, JobHandler
from ahq.runtime.conversations import Conversations
from ahq.runtime.qa import QaReviews
from ahq.runtime.segment import SegmentRunner
from ahq.sim.control import SimControl

logger = logging.getLogger(__name__)

JOB_TYPES: Mapping[Topic, type[Job]] = {
    Topic.WORK: SegmentJob,
    Topic.SIM: SimTickJob,
    Topic.CUSTOMER: CustomerTurnJob,
    Topic.QA: QaReviewJob,
}


def parse_job(topic: Topic, payload: Mapping[str, Any]) -> Job:
    return JOB_TYPES[topic].model_validate(payload)


def build_handlers(
    runner: SegmentRunner,
    sim: SimControl | None = None,
    conversations: Conversations | None = None,
    reviews: QaReviews | None = None,
    *,
    before: Callable[[], Awaitable[object]] | None = None,
) -> dict[Topic, JobHandler]:
    async def handle_work(job: Job, delivery: Delivery) -> None:
        await runner.run(SegmentJob.model_validate(job.model_dump()))

    handlers: dict[Topic, JobHandler] = {Topic.WORK: handle_work}
    if sim is not None:

        async def handle_sim(job: Job, delivery: Delivery) -> None:
            await sim.tick(SimTickJob.model_validate(job.model_dump()))

        handlers[Topic.SIM] = handle_sim
    if conversations is not None:

        async def handle_customer(job: Job, delivery: Delivery) -> None:
            await conversations.turn(CustomerTurnJob.model_validate(job.model_dump()))

        handlers[Topic.CUSTOMER] = handle_customer
    if reviews is not None:

        async def handle_qa(job: Job, delivery: Delivery) -> None:
            await reviews.review(QaReviewJob.model_validate(job.model_dump()))

        handlers[Topic.QA] = handle_qa
    return {topic: _deferring(handler, before) for topic, handler in handlers.items()}


def _deferring(handler: JobHandler, before: Callable[[], Awaitable[object]] | None) -> JobHandler:
    async def handle(job: Job, delivery: Delivery) -> None:
        if before is not None:
            await before()
        try:
            await handler(job, delivery)
        except NotFoundError as error:
            logger.warning("dropped %s job %s: %s", job.topic, job.job_id, error)
        except Exception as error:
            later = deferral(error)
            if later is None or later is error:
                raise
            raise later from error

    return handle
