from __future__ import annotations

import difflib

from fastapi import APIRouter, Query
from pydantic import Field, JsonValue

from ahq.api.deps import ContainerDep, Operator
from ahq.domain import AgentVersion, EvalRun, GateParams, NotFoundError, StrictModel, VersionConfig

router = APIRouter(tags=["versions"])


class NewVersion(StrictModel):
    config: VersionConfig
    note: str = Field(min_length=3, description="What changed and why, for the timeline.")


class CanaryRequest(StrictModel):
    pct: int = Field(ge=1, le=100)
    skip_gate: bool = Field(default=False, description="Start a draft without the eval gate; the timeline says so.")


class PromoteRequest(StrictModel):
    reason: str = Field(min_length=3)
    force: bool = Field(default=False, description="Promote a draft or evaluated version without a canary.")


class ReasonRequest(StrictModel):
    reason: str = Field(min_length=3)


class FieldChange(StrictModel):
    field: str
    before: JsonValue
    after: JsonValue


class VersionDiff(StrictModel):
    before: str
    after: str
    changes: list[FieldChange]
    prompt: list[str] = Field(description="Unified diff lines of the whole prompt.")


@router.get("/api/versions")
async def list_versions(container: ContainerDep, agent: str | None = None) -> list[AgentVersion]:
    return await container.versions.store.list(agent)


@router.get("/api/versions/{version_id}")
async def get_version(version_id: str, container: ContainerDep) -> AgentVersion:
    return await container.versions.get(version_id)


@router.get("/api/versions/{version_id}/diff")
async def diff_version(
    version_id: str,
    container: ContainerDep,
    against: str | None = Query(default=None, description="The version to compare with; by default its parent."),
) -> VersionDiff:
    after = await container.versions.get(version_id)
    base_id = against or after.parent_id
    if base_id is None:
        raise NotFoundError(f"{version_id} has no parent to compare with")
    before = await container.versions.get(base_id)
    return version_diff(before, after)


def version_diff(before: AgentVersion, after: AgentVersion) -> VersionDiff:
    old, new = before.config, after.config
    changes = [
        FieldChange(field=name, before=getattr(old, name), after=getattr(new, name))
        for name in ("model", "tools", "max_model_calls", "max_usd")
        if getattr(old, name) != getattr(new, name)
    ]
    prompt = list(
        difflib.unified_diff(
            f"{old.prompt_stable}\n\n{old.prompt_context}".splitlines(),
            f"{new.prompt_stable}\n\n{new.prompt_context}".splitlines(),
            fromfile=before.version_id,
            tofile=after.version_id,
            lineterm="",
            n=2,
        )
    )
    return VersionDiff(before=before.version_id, after=after.version_id, changes=changes, prompt=prompt)


@router.post("/api/agents/{agent}/versions")
async def create_version(agent: str, request: NewVersion, container: ContainerDep, operator: Operator) -> AgentVersion:
    return await container.versions.draft(agent, request.config, note=request.note, by=operator)


@router.post("/api/versions/{version_id}/gate")
async def request_gate(
    version_id: str, container: ContainerDep, operator: Operator, params: GateParams | None = None
) -> EvalRun:
    return await container.evals.request(version_id, by=operator, params=params)


@router.post("/api/versions/{version_id}/canary")
async def start_canary(
    version_id: str, request: CanaryRequest, container: ContainerDep, operator: Operator
) -> AgentVersion:
    return await container.versions.start_canary(version_id, pct=request.pct, by=operator, skip_gate=request.skip_gate)


@router.post("/api/versions/{version_id}/promote")
async def promote(
    version_id: str, request: PromoteRequest, container: ContainerDep, operator: Operator
) -> AgentVersion:
    return await container.versions.promote(version_id, by=operator, reason=request.reason, force=request.force)


@router.post("/api/versions/{version_id}/rollback")
async def roll_back(
    version_id: str, request: ReasonRequest, container: ContainerDep, operator: Operator
) -> AgentVersion:
    return await container.versions.roll_back(version_id, by=operator, reasons=[request.reason])


@router.post("/api/versions/{version_id}/retire")
async def retire(version_id: str, request: ReasonRequest, container: ContainerDep, operator: Operator) -> AgentVersion:
    return await container.versions.retire(version_id, by=operator, reason=request.reason)
