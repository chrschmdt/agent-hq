from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Iterator
from contextlib import AsyncExitStack, contextmanager
from typing import Any

from vercel.queue import RetryAfter, subscribe

from ahq.adapters.clock import WallClock
from ahq.app.container import Container, Overrides, open_container
from ahq.domain import CustomerTurnJob, QaReviewJob, SegmentJob, SimTickJob, Topic, deferral
from ahq.settings import get_settings

log = logging.getLogger(__name__)


def _since_boot() -> str:
    boot_ms = os.environ.get("__VC_PY_BOOT_START_MS")
    return f"{time.monotonic() - int(boot_ms) / 1000:.2f}s" if boot_ms else "unknown"


@contextmanager
def _deferring() -> Iterator[None]:
    try:
        yield
    except Exception as error:
        later = deferral(error)
        if later is None:
            raise
        raise RetryAfter(later.after_seconds, reason=later.reason) from error


class _Instance:
    stack = AsyncExitStack()
    container: Container | None = None
    lock = asyncio.Lock()

    @classmethod
    async def container_(cls) -> Container:
        async with cls.lock:
            if cls.container is None:
                started = time.monotonic()
                cls.container = await cls.stack.enter_async_context(
                    open_container(get_settings(), overrides=Overrides(clock=WallClock(), follow_model_choice=True))
                )
                log.info("container opened in %.2fs, %s after boot", time.monotonic() - started, _since_boot())
            await cls.container.model_switch.refresh()
            return cls.container


@subscribe(topic=Topic.WORK.value, retry_after=30, max_attempts=5)
async def handle_work(payload: dict[str, Any]) -> None:
    job = SegmentJob.model_validate(payload)
    container = await _Instance.container_()
    started = time.monotonic()
    try:
        with _deferring():
            await container.runner.run(job)
    finally:
        log.info("%s segment for %s took %.2fs", job.action, job.work_item_id, time.monotonic() - started)


@subscribe(topic=Topic.SIM.value, retry_after=5, max_attempts=3)
async def handle_sim(payload: dict[str, Any]) -> None:
    job = SimTickJob.model_validate(payload)
    container = await _Instance.container_()
    with _deferring():
        await container.sim.tick(job)


@subscribe(topic=Topic.CUSTOMER.value, retry_after=10, max_attempts=3)
async def handle_customer(payload: dict[str, Any]) -> None:
    job = CustomerTurnJob.model_validate(payload)
    container = await _Instance.container_()
    with _deferring():
        await container.conversations.turn(job)


@subscribe(topic=Topic.QA.value, retry_after=30, max_attempts=3)
async def handle_qa(payload: dict[str, Any]) -> None:
    job = QaReviewJob.model_validate(payload)
    container = await _Instance.container_()
    with _deferring():
        await container.reviews.review(job)
