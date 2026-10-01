from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import computed_field

from ahq.api.deps import ContainerDep
from ahq.domain import StrictModel

router = APIRouter(tags=["health"])


class Health(StrictModel):
    status: Literal["ok"]
    environment: str
    profile: str
    storage: str
    queue: str


class DeepHealth(StrictModel):
    database: bool
    qdrant: bool


class Status(StrictModel):
    active_work: int
    pending_approvals: int
    simulating: bool = False
    last_event_id: int

    @computed_field
    @property
    def active(self) -> bool:
        return self.active_work > 0 or self.pending_approvals > 0 or self.simulating


@router.get("/api/health")
async def health(container: ContainerDep) -> Health:
    settings = container.settings
    return Health(
        status="ok",
        environment=settings.environment,
        profile=container.model_switch.current,
        storage=container.storage,
        queue=settings.queue_backend,
    )


@router.get("/api/health/deep")
async def deep_health(container: ContainerDep) -> DeepHealth:
    database = qdrant = True
    try:
        await container.events.last_id()
    except Exception:
        database = False
    try:
        await container.vector_store.collection_names()
    except Exception:
        qdrant = False
    return DeepHealth(database=database, qdrant=qdrant)


@router.get("/api/status")
async def status(container: ContainerDep) -> Status:
    latest = await container.sim_runs.latest()
    return Status(
        active_work=await container.work.count_active(),
        pending_approvals=len(await container.approvals.pending()),
        simulating=latest is not None and latest.status == "running",
        last_event_id=await container.events.last_id(),
    )
