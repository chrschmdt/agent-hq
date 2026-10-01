from __future__ import annotations

from fastapi import APIRouter, Depends

from ahq.api.deps import ContainerDep, require_cron
from ahq.domain import StrictModel

router = APIRouter(tags=["cron"], dependencies=[Depends(require_cron)])


class Keepalive(StrictModel):
    collections: int


@router.get("/api/cron/qdrant-keepalive")
async def qdrant_keepalive(container: ContainerDep) -> Keepalive:
    return Keepalive(collections=len(await container.vector_store.collection_names()))
