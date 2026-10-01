from __future__ import annotations

import pytest

from ahq.adapters.clock import ManualClock
from ahq.adapters.memory import MemoryEventLog
from ahq.adapters.memory_management import MemoryControlStore
from ahq.config import ModelRole, ProfileName
from ahq.domain import ConflictError, EventKind
from ahq.management import ModelSwitch, SwitchingChatModels
from ahq.testing import FakeChatModels


class NamedModels(FakeChatModels):
    def __init__(self, profile: ProfileName) -> None:
        super().__init__()
        self.profile = profile

    def model_key(self, role: ModelRole, preferred: str | None = None) -> str:
        return f"{self.profile}:{role}"


def switch(store: MemoryControlStore, clock: ManualClock, events: MemoryEventLog | None = None) -> ModelSwitch:
    return ModelSwitch(
        "low", available=["mock", "low", "high"], store=store, events=events or MemoryEventLog(clock), clock=clock
    )


async def test_a_choice_reaches_every_instance_at_its_next_refresh(clock: ManualClock) -> None:
    store, events = MemoryControlStore(), MemoryEventLog(clock)
    admin, worker = switch(store, clock, events), switch(store, clock)
    assert (admin.current, worker.current) == ("low", "low")

    choice = await admin.choose("high", by="operator")

    assert (choice.profile, choice.changed_by, admin.current, worker.current) == ("high", "operator", "high", "low")
    assert await worker.refresh() == "high"
    (event,) = await events.read_after(0, limit=10)
    assert (event.kind, event.payload) == (EventKind.MODELS_SWITCHED, {"profile": "high", "previous": "low"})


async def test_a_profile_the_deployment_cannot_play_is_refused_and_never_followed(clock: ManualClock) -> None:
    store = MemoryControlStore()
    with pytest.raises(ConflictError, match="OPENROUTER_API_KEY"):
        await switch(store, clock).choose("medium", by="operator")
    keyless = ModelSwitch("mock", available=["mock"], store=store, clock=clock)
    await switch(store, clock).choose("high", by="operator")
    assert await keyless.refresh() == "mock"


async def test_without_a_store_the_profile_is_fixed(clock: ManualClock) -> None:
    fixed = ModelSwitch("medium", available=["mock", "medium"])
    assert (fixed.switchable, await fixed.refresh()) == (False, "medium")
    with pytest.raises(ConflictError, match="fixed"):
        await fixed.choose("mock", by="operator")


async def test_calls_go_to_the_current_profiles_models(clock: ManualClock) -> None:
    chooser = switch(MemoryControlStore(), clock)
    built: list[ProfileName] = []

    def build(profile: ProfileName) -> NamedModels:
        built.append(profile)
        return NamedModels(profile)

    models = SwitchingChatModels(chooser, build)
    assert models.model_key("support") == "low:support"
    await chooser.choose("high", by="operator")
    assert models.model_key("support") == "high:support"
    await chooser.choose("low", by="operator")
    assert models.model_key("dispatcher") == "low:dispatcher"
    assert built == ["low", "high"]
