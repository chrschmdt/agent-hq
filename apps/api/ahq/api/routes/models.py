from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from ahq.api.deps import ContainerDep, Operator
from ahq.config import ModelRole, ProfileName
from ahq.domain import StrictModel

router = APIRouter(tags=["models"])

ROLES: tuple[ModelRole, ...] = (
    "dispatcher",
    "support",
    "ops",
    "insights",
    "guard",
    "qa",
    "customer",
    "writer",
    "smoke",
)


class CatalogModel(StrictModel):
    key: str
    id: str
    provider: str
    input: float
    output: float
    cache_read: float
    cache_write: float
    reasoning: bool
    fallback: str | None


class ProfileView(StrictModel):
    name: ProfileName
    roles: dict[str, str]
    available: bool
    version_models: bool


class PricedModel(StrictModel):
    id: str
    price: float


class ModelsView(StrictModel):
    profile: ProfileName
    default: ProfileName
    switchable: bool
    chosen_by: str | None
    chosen_at: datetime | None
    profiles: list[ProfileView]
    models: list[CatalogModel]
    embeddings: PricedModel
    rerank: PricedModel


class ProfileRequest(StrictModel):
    profile: ProfileName


@router.get("/api/models")
async def models(container: ContainerDep) -> ModelsView:
    return await _view(container)


@router.put("/api/models/profile")
async def choose_profile(request: ProfileRequest, container: ContainerDep, operator: Operator) -> ModelsView:
    await container.model_switch.choose(request.profile, by=operator)
    return await _view(container)


async def _view(container: ContainerDep) -> ModelsView:
    switch = container.model_switch
    await switch.refresh()
    choice = await switch.choice()
    catalog = container.catalog
    return ModelsView(
        profile=switch.current,
        default=switch.default,
        switchable=switch.switchable,
        chosen_by=choice.changed_by if choice else None,
        chosen_at=choice.changed_at if choice else None,
        profiles=[
            ProfileView(
                name=name,
                roles={role: catalog.resolve(name, role)[0] for role in ROLES},
                available=name in switch.available,
                version_models=name in catalog.version_models,
            )
            for name in catalog.profiles
        ],
        models=[
            CatalogModel(
                key=key,
                id=spec.id,
                provider=spec.id.split("/", 1)[0] if "/" in spec.id else spec.route,
                input=spec.input,
                output=spec.output,
                cache_read=spec.cache_read,
                cache_write=spec.cache_write,
                reasoning=spec.reasoning is not None,
                fallback=spec.fallback,
            )
            for key, spec in catalog.models.items()
        ],
        embeddings=PricedModel(id=catalog.embeddings.id, price=catalog.embeddings.price),
        rerank=PricedModel(id=catalog.rerank.id, price=catalog.rerank.price),
    )
