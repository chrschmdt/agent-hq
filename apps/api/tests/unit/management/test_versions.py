from __future__ import annotations

from dataclasses import replace

import pytest

from ahq.adapters.memory_management import MemoryVersionStore
from ahq.agents import SPECS, SUPPORT, PromptTemplate, version_config
from ahq.domain import ConflictError, InvalidRequest, VersionStatus
from ahq.scorecards import bucket
from tests.unit.management.helpers import Desk


async def test_code_seeds_one_live_version_per_agent_once() -> None:
    desk = Desk()
    created = await desk.registry.sync()
    again = await desk.registry.sync()

    assert sorted(v.version_id for v in created) == sorted(f"{name}@1" for name in SPECS)
    assert again == []
    assert all(v.status is VersionStatus.LIVE and v.created_by == "code" for v in created)


async def test_a_prompt_changed_in_code_becomes_a_draft_not_live() -> None:
    desk = Desk()
    await desk.registry.sync()
    edited = replace(SUPPORT, prompt=PromptTemplate(SUPPORT.prompt.stable + "\n\nBe brief.", SUPPORT.prompt.context))

    [draft] = await desk.registry.sync([edited])

    assert (draft.version_id, draft.status, draft.parent_id) == ("support@2", VersionStatus.DRAFT, "support@1")
    assert (await desk.registry.pin("support", "wi_1")).version_id == "support@1"


async def test_drafts_are_validated_and_unique() -> None:
    desk = Desk()
    await desk.registry.sync()
    config = version_config(SUPPORT)
    with pytest.raises(InvalidRequest, match="tools not granted"):
        await desk.registry.draft(
            "support", config.model_copy(update={"tools": ["analytics_run_sql"]}), note="x", by="op"
        )
    with pytest.raises(ConflictError, match="support@1 already has this configuration"):
        await desk.registry.draft("support", config, note="the same", by="op")


async def test_a_canary_takes_its_share_of_work_and_keeps_it() -> None:
    desk = Desk()
    await desk.registry.sync()
    brief = version_config(SUPPORT).model_copy(update={"prompt_stable": SUPPORT.prompt.stable + "\n\nBe brief."})
    draft = await desk.registry.draft("support", brief, note="Shorter replies.", by="op")
    with pytest.raises(ConflictError):
        await desk.registry.start_canary(draft.version_id, pct=30, by="op")
    await desk.registry.start_canary(draft.version_id, pct=30, by="op", skip_gate=True)

    ids = [f"wi_{n}" for n in range(200)]
    pinned = {work_item_id: (await desk.registry.pin("support", work_item_id)).version_id for work_item_id in ids}
    expected = {i: "support@2" if bucket(i, "support", 30) else "support@1" for i in ids}
    assert pinned == expected
    assert 0.2 < list(pinned.values()).count("support@2") / len(ids) < 0.4
    assert (await desk.registry.spec("support@2")).prompt.stable.endswith("Be brief.")


async def test_the_lifecycle_from_gate_to_live_is_on_the_timeline() -> None:
    desk = Desk()
    await desk.registry.sync()
    config = version_config(SUPPORT).model_copy(update={"max_model_calls": 12})
    draft = await desk.registry.draft("support", config, note="Fewer calls.", by="op")

    evaluated = await desk.registry.record_eval(draft.version_id, {"passed": True}, passed=True)
    canary = await desk.registry.start_canary(draft.version_id, pct=20, by="op")
    live = await desk.registry.promote(draft.version_id, by="canary", reason="clean")

    assert (evaluated.status, canary.status, live.status) == (
        VersionStatus.EVALUATED,
        VersionStatus.CANARY,
        VersionStatus.LIVE,
    )
    assert (await desk.registry.get("support@1")).status is VersionStatus.RETIRED
    assert (await desk.kinds())[-4:] == [
        "version.created",
        "version.evaluated",
        "version.canary_started",
        "version.promoted",
    ]


async def test_a_rolled_back_change_can_ship_again_only_by_skipping_the_gate() -> None:
    desk = Desk()
    await desk.registry.sync()
    change = {"max_model_calls": 2}
    first = await desk.registry.canary_change("support", changes=change, pct=50, note="cheaper", by="scenario")
    await desk.registry.roll_back(first.version_id, by="canary", reasons=["worse"])
    again = await desk.registry.canary_change("support", changes=change, pct=50, note="cheaper", by="scenario")

    assert again.version_id == first.version_id
    assert again.config.max_model_calls == 2
    assert again.status is VersionStatus.CANARY
    assert again.status_reason == "canary on 50% of new work, without the eval gate"


async def test_a_version_drafted_after_the_versions_are_cleared_runs_as_drafted() -> None:
    desk = Desk()
    await desk.registry.sync()
    first = version_config(SUPPORT).model_copy(update={"prompt_stable": SUPPORT.prompt.stable + "\n\nBe brief."})
    await desk.registry.draft("support", first, note="Shorter replies.", by="op")
    assert "Be brief." in (await desk.registry.spec("support@2")).prompt.stable

    store = desk.registry.store
    assert isinstance(store, MemoryVersionStore)
    store.clear_versions()
    await desk.registry.sync()
    second = version_config(SUPPORT).model_copy(update={"prompt_stable": SUPPORT.prompt.stable + "\n\nBe warm."})
    await desk.registry.draft("support", second, note="Warmer replies.", by="op")
    assert "Be warm." in (await desk.registry.spec("support@2")).prompt.stable
