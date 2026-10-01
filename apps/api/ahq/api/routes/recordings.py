from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import Field

from ahq.api.deps import ContainerDep, IsOperator, Operator
from ahq.api.recordings import Recording, record_day
from ahq.domain import NotFoundError, StrictModel
from ahq.domain.recordings import RecordingInfo

PUBLISHED_CACHE = "public, max-age=300, s-maxage=3600, stale-while-revalidate=3600"

router = APIRouter(tags=["recordings"])


class RecordRequest(StrictModel):
    sim_run_id: str
    title: str | None = Field(default=None, min_length=1, max_length=120)


class RecordingChange(StrictModel):
    published: bool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)


@router.get("/api/recordings")
async def list_recordings(container: ContainerDep, operator: IsOperator) -> list[RecordingInfo]:
    return await container.recordings.list(published_only=not operator)


@router.get(
    "/api/recordings/{recording_id}",
    response_class=Response,
    responses={200: {"model": Recording, "description": "The recorded day, sent gzip-compressed as stored."}},
)
async def get_recording(recording_id: str, container: ContainerDep, operator: IsOperator) -> Response:
    info = await container.recordings.get(recording_id)
    bundle = await container.recordings.bundle(recording_id) if info and (info.published or operator) else None
    if info is None or bundle is None:
        raise NotFoundError(f"recording {recording_id} not found")
    return Response(
        content=bundle,
        media_type="application/json",
        headers={
            "Content-Encoding": "gzip",
            "Cache-Control": PUBLISHED_CACHE if info.published else "private, no-store",
        },
    )


@router.post("/api/recordings")
async def record(request: RecordRequest, container: ContainerDep, operator: Operator) -> RecordingInfo:
    return await record_day(container, request.sim_run_id, title=request.title, by=operator)


@router.patch("/api/recordings/{recording_id}")
async def change_recording(
    recording_id: str, request: RecordingChange, container: ContainerDep, _: Operator
) -> RecordingInfo:
    return await container.recordings.update(recording_id, published=request.published, title=request.title)


@router.delete("/api/recordings/{recording_id}", status_code=204)
async def delete_recording(recording_id: str, container: ContainerDep, _: Operator) -> None:
    await container.recordings.delete(recording_id)
