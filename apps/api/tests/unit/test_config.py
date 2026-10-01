from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import ahq.agents
from ahq.config import ModelCatalog, ProfileName, WorldConfig, load_model_catalog, load_world_config
from ahq.domain import Price, Usage, cost_usd
from ahq.domain.retail import RetailSnapshot
from tests.conftest import TAU3_DIR


def test_every_profile_resolves_every_role() -> None:
    catalog = load_model_catalog()
    for profile, roles in catalog.profiles.items():
        for role in roles:
            key, spec = catalog.resolve(profile, role)
            assert spec is catalog.models[key]


def test_the_mock_profile_never_leaves_the_process() -> None:
    catalog = load_model_catalog()
    assert {spec.route for _, spec in (catalog.resolve("mock", role) for role in catalog.profiles["mock"])} == {"fake"}


def test_the_judge_comes_from_a_different_family_than_the_agents_on_medium_and_high() -> None:
    catalog = load_model_catalog()
    for profile in ("medium", "high"):
        _, judge = catalog.resolve(profile, "qa")
        _, support = catalog.resolve(profile, "support")
        assert judge.route != support.route


def test_profiles_step_up_in_price() -> None:
    catalog = load_model_catalog()

    def output_price(profile: ProfileName) -> float:
        return sum(catalog.resolve(profile, role)[1].output for role in ("support", "ops", "insights"))

    assert output_price("mock") < output_price("low") < output_price("medium") < output_price("high")


def test_profiles_must_cover_every_role() -> None:
    raw = load_model_catalog().model_dump()
    del raw["profiles"]["low"]["qa"]
    with pytest.raises(ValueError, match="missing roles"):
        ModelCatalog.model_validate(raw)


def test_cost_prices_each_token_category_separately() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_tokens=2_000_000, cache_write_tokens=0)
    price = Price(input=1.0, output=5.0, cache_read=0.1, cache_write=1.25)
    assert cost_usd(usage, price) == pytest.approx(1.0 + 0.5 + 0.2)


def test_usage_adds_up() -> None:
    total = Usage(input_tokens=1, output_tokens=2) + Usage(input_tokens=3, cache_read_tokens=4)
    assert total == Usage(input_tokens=4, output_tokens=2, cache_read_tokens=4)


def test_every_store_product_has_a_category_and_every_state_a_region(tau3_snapshot: RetailSnapshot) -> None:
    world = load_world_config()
    assert {product.name for product in tau3_snapshot.products.values()} == {
        name for names in world.categories.values() for name in names
    }
    states = {user.address.state for user in tau3_snapshot.users.values()}
    assert states <= {state for states in world.regions.values() for state in states}


def test_the_stores_day_turns_at_its_own_midnight_not_at_utc_midnight() -> None:
    clock = load_world_config().clock
    assert clock.day_at(datetime(2026, 6, 16, 0, 35, tzinfo=UTC)) == date(2026, 6, 15)
    assert clock.day_at(datetime(2026, 6, 16, 4, 5, tzinfo=UTC)) == date(2026, 6, 16)


def test_carrier_shares_must_add_up() -> None:
    raw = load_world_config().model_dump()
    raw["carriers"][0]["share"] = 0.9
    with pytest.raises(ValueError, match="shares"):
        WorldConfig.model_validate(raw)


def test_supports_packaged_policy_is_the_vendored_tau3_policy() -> None:
    packaged = Path(ahq.agents.__file__).parent / "support" / "tau3_policy.md"
    assert packaged.read_text() == (TAU3_DIR / "policy.md").read_text()


def test_a_forced_role_plays_its_model_under_every_profile_and_over_a_versions_choice() -> None:
    catalog = load_model_catalog().forcing({"support": "claude-haiku-4-5"})
    assert catalog.resolve("low", "support")[0] == "claude-haiku-4-5"
    assert catalog.resolve("high", "support", "claude-sonnet-5-5")[0] == "claude-haiku-4-5"
    assert catalog.resolve("low", "dispatcher")[0] == "gpt-6-luna"
    with pytest.raises(ValueError, match="unknown forced models"):
        load_model_catalog().forcing({"support": "no-such-model"})


def test_every_model_an_agent_can_play_on_falls_back_to_a_known_model() -> None:
    catalog = load_model_catalog()
    for profile in ("low", "medium", "high"):
        for role in ("dispatcher", "support", "ops", "insights", "qa", "guard"):
            key, spec = catalog.resolve(profile, role)
            assert spec.fallback is not None, (profile, role, key)
            assert spec.fallback != key
