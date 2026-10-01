from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ahq.agents import (
    SPECS,
    SUPPORT,
    CodeBook,
    all_problems,
    spec_from_version,
    validate_version,
    version_config,
)
from ahq.config import load_model_catalog
from ahq.domain import AgentVersion, VersionConfig, VersionStatus
from ahq.tools import CATALOG

MODELS = load_model_catalog().models.keys()
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


def test_every_code_spec_is_valid() -> None:
    assert all_problems(SPECS.values(), CATALOG) == []


@pytest.mark.parametrize("name", sorted(SPECS))
def test_the_stable_prompt_is_identical_across_work_items(name: str) -> None:
    spec = SPECS[name]
    values = {"today": "2026-06-15", "now": "2026-06-15T10:00", "ticket_id": "tk_1", "work_item_id": "wi_1"}
    first = spec.prompt.render(values)
    second = spec.prompt.render({**values, "ticket_id": "tk_2", "work_item_id": "wi_2"})
    assert first.stable == second.stable
    assert first.stable.encode() == spec.prompt.stable.encode()


def test_a_version_round_trips_through_its_configuration() -> None:
    config = version_config(SUPPORT)
    version = AgentVersion(
        version_id="support@1",
        agent="support",
        number=1,
        status=VersionStatus.LIVE,
        config=config,
        digest=config.digest,
        created_by="code",
        created_at=NOW,
        status_at=NOW,
    )
    assert spec_from_version(SUPPORT, version) == SUPPORT


def change(**fields: object) -> VersionConfig:
    return version_config(SUPPORT).model_copy(update=fields)


def test_a_version_may_drop_tools_and_change_its_model_prompt_and_limits() -> None:
    config = change(
        model="claude-sonnet-5-5",
        prompt_stable=SUPPORT.prompt.stable + "\n\nBe brief.",
        tools=[tool for tool in SUPPORT.tools if tool != "knowledge_get_article"],
        max_model_calls=10,
        max_usd=0.2,
    )
    assert validate_version(SUPPORT, config, CATALOG, MODELS) == []
    assert config.digest != version_config(SUPPORT).digest


@pytest.mark.parametrize(
    ("config", "problem"),
    [
        (change(tools=[*SUPPORT.tools, "analytics_run_sql"]), "tools not granted to support: analytics_run_sql"),
        (change(model="gpt-7"), "unknown model gpt-7"),
        (change(prompt_stable="Hello {name}"), "placeholders before '## Context': ['name']"),
        (change(prompt_context="Today is {today}."), "the context part must start with '## Context'"),
        (change(prompt_context="## Context\n\n{secret}"), "unexpected prompt placeholders ['secret']"),
        (
            change(tools=[tool for tool in SUPPORT.tools if tool not in ("knowledge_search",)]),
            "checking citations needs knowledge_search and a reply with citations",
        ),
    ],
)
def test_a_version_may_not_change_what_code_decides(config: VersionConfig, problem: str) -> None:
    assert [p.problem for p in validate_version(SUPPORT, config, CATALOG, MODELS)] == [problem]


async def test_the_code_book_runs_code_specs() -> None:
    book = CodeBook()
    assert await book.pin("support", "wi_1") == SUPPORT
    assert await book.spec("support@7") == SUPPORT
