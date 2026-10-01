from __future__ import annotations

from fastapi import APIRouter

from ahq.api.deps import ContainerDep, Operator
from ahq.domain import ActivityReport, StrictModel

router = APIRouter(tags=["activity"])


class ClearRequest(StrictModel):
    versions: bool = False


@router.post("/api/activity/clear")
async def clear_activity(request: ClearRequest, container: ContainerDep, operator: Operator) -> ActivityReport:
    return await container.activity.clear(versions=request.versions, by=operator)
