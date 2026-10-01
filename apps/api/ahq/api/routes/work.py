from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import Field, JsonValue

from ahq.api.deps import ContainerDep, Operator
from ahq.domain import Event, StrictModel, WorkItem, WorkItemId, WorkKind, WorkStatus

router = APIRouter(tags=["work"])


class SubmitWork(StrictModel):
    kind: WorkKind
    input: dict[str, JsonValue] = Field(default_factory=dict)


class WorkDetail(StrictModel):
    item: WorkItem
    events: list[Event]


@router.post("/api/work", status_code=status.HTTP_202_ACCEPTED)
async def submit_work(body: SubmitWork, container: ContainerDep, operator: Operator) -> WorkItem:
    return await container.commands.submit_work(body.kind, body.input, actor=operator)


@router.get("/api/work")
async def list_work(
    container: ContainerDep,
    status: Annotated[list[WorkStatus] | None, Query()] = None,
    kind: Annotated[list[WorkKind] | None, Query()] = None,
    owner: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[WorkItem]:
    return await container.work.list(statuses=status, kinds=kind, owner=owner, limit=limit)


@router.get("/api/work/{work_item_id}")
async def get_work(work_item_id: WorkItemId, container: ContainerDep) -> WorkDetail:
    return WorkDetail(
        item=await container.work.get(work_item_id),
        events=await container.events.for_work_item(work_item_id),
    )


class Cancellation(StrictModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/api/work/{work_item_id}/cancel")
async def cancel_work(
    work_item_id: WorkItemId, body: Cancellation, container: ContainerDep, operator: Operator
) -> WorkItem:
    return await container.commands.cancel_work(work_item_id, actor=operator, reason=body.reason)
