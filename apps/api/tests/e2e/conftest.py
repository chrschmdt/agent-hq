from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import FastAPI

from ahq.adapters.queue_inprocess import InProcessQueue
from ahq.api.factory import create_app
from ahq.app.container import Container, Overrides
from tests.conftest import make_settings

OPERATOR = {"Authorization": "Bearer test-operator-token"}


@dataclass
class Running:
    app: FastAPI
    http: httpx.AsyncClient

    @property
    def container(self) -> Container:
        return self.app.state.container

    @property
    def queue(self) -> InProcessQueue:
        queue = self.container.inprocess_queue
        assert queue is not None
        return queue


@asynccontextmanager
async def running(overrides: Overrides | None = None, /, **settings: object) -> AsyncIterator[Running]:
    app = create_app(make_settings(**settings), overrides=overrides, run_queue_worker=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as http,
    ):
        yield Running(app, http)
