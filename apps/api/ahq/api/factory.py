from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI

from ahq.adapters.clock import WallClock
from ahq.api.errors import install_error_handlers
from ahq.api.recordings import publish_file
from ahq.api.routes import (
    activity,
    agents,
    approvals,
    cron,
    evals,
    events,
    health,
    insight,
    management,
    models,
    quality,
    recordings,
    runs,
    sim,
    store,
    team,
    tickets,
    versions,
    work,
)
from ahq.app.container import Container, Overrides, open_container
from ahq.domain import EvalJob, Job, Topic
from ahq.evals.gate import run_queued
from ahq.mcp_servers import run_mounts
from ahq.ports import Delivery
from ahq.settings import Settings, get_settings

API_VERSION = "0.1.0"

log = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    overrides: Overrides | None = None,
    run_queue_worker: bool = True,
) -> FastAPI:
    settings = settings or get_settings()
    overrides = overrides or Overrides()
    clock = overrides.clock or WallClock()
    overrides = dataclasses.replace(overrides, clock=clock, follow_model_choice=True)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        started = time.monotonic()
        async with open_container(settings, overrides=overrides) as container, run_mounts(container.mcp.mounts):
            app.state.container = container
            _run_evals_here(container)
            seeded = container.storage == "memory" and container.settings.seed_memory
            if seeded and container.settings.offline_recording.is_file():
                await publish_file(container, container.settings.offline_recording, by="offline")
            routes = [mount.route for mount in container.mcp.mounts]
            app.router.routes.extend(routes)
            log.info("api container opened in %.2fs", time.monotonic() - started)
            stop = asyncio.Event()
            worker = None
            if run_queue_worker and container.inprocess_queue is not None:
                concurrency = container.settings.queue_concurrency
                worker = asyncio.create_task(container.inprocess_queue.run_forever(stop, concurrency=concurrency))
            try:
                yield
            finally:
                stop.set()
                if worker is not None:
                    await worker
                for route in routes:
                    app.router.routes.remove(route)

    app = FastAPI(
        title="AHQ",
        version=API_VERSION,
        summary="A team of AI agents running customer operations, and the control room that manages them.",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    install_error_handlers(app)
    routers = (
        health.router,
        events.router,
        work.router,
        tickets.router,
        runs.router,
        approvals.router,
        team.router,
        agents.router,
        versions.router,
        management.router,
        models.router,
        quality.router,
        evals.router,
        insight.router,
        sim.router,
        store.router,
        recordings.router,
        activity.router,
        cron.router,
    )
    for router in routers:
        app.include_router(router)
    return app


def _run_evals_here(container: Container) -> None:
    queue = container.inprocess_queue
    if queue is None:
        return

    async def handle(job: Job, delivery: Delivery) -> None:
        await run_queued(container, EvalJob.model_validate(job.model_dump()).eval_run_id)

    queue.register(Topic.EVAL, handle)
