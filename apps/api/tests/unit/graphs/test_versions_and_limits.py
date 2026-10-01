from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace

import pytest
from langchain_core.messages import HumanMessage

from ahq.agents import SPECS, SUPPORT, AgentSpec, PromptTemplate
from ahq.domain import CallDecision, EventKind
from ahq.domain.world import TicketMessage
from ahq.graphs import HANDOFF_REPLY
from ahq.retrieval import ingest, load_documents
from ahq.settings import REPO_ROOT
from ahq.testing import HashEmbedder, HashingSparse
from ahq.testing.qdrant import LocalVectorStore
from tests.unit.graphs.harness import NOW, Harness, calls, reply, route

BRIEF = PromptTemplate(SUPPORT.prompt.stable + "\n\nBe brief.", SUPPORT.prompt.context)
CANARY = replace(SUPPORT, version=2, prompt=BRIEF)


class TwoVersions:
    def __init__(self) -> None:
        self.canary = True
        self.pins: list[tuple[str, str]] = []

    async def pin(self, agent: str, work_item_id: str) -> AgentSpec:
        self.pins.append((agent, work_item_id))
        return CANARY if agent == "support" and self.canary else SPECS[agent]

    async def spec(self, version_id: str) -> AgentSpec:
        return CANARY if version_id == "support@2" else SPECS[version_id.partition("@")[0]]


class Switches:
    def __init__(self) -> None:
        self.paused_agents: set[str] = set()
        self.spent: set[str] = set()
        self.fallback: dict[str, str] = {}
        self.calls: list[tuple[str, str, bool]] = []

    async def before_call(self, agent: str, model: str) -> CallDecision:
        if agent in self.paused_agents:
            return CallDecision(verdict="pause", model=model, reason="paused")
        if agent in self.spent:
            return CallDecision(verdict="deny", model=model, reason="spent")
        if model in self.fallback:
            return CallDecision(verdict="fallback", model=self.fallback[model])
        return CallDecision(verdict="proceed", model=model)

    async def after_call(self, agent: str, model: str, *, cost_usd: float, ok: bool, error: str | None = None) -> None:
        self.calls.append((agent, model, ok))

    async def paused(self) -> frozenset[str]:
        return frozenset(self.paused_agents)


@pytest.fixture
async def store() -> AsyncIterator[LocalVectorStore]:
    vectors = LocalVectorStore()
    await ingest(vectors, HashEmbedder(), HashingSparse(), load_documents(REPO_ROOT / "kb"))
    yield vectors
    await vectors.close()


async def test_a_ticket_stays_with_the_version_that_took_it(store: LocalVectorStore) -> None:
    book = TwoVersions()
    harness = Harness(store, agents=book)
    harness.models.script("support", reply("Which order?"), reply("Thanks, done.", status="resolved"))
    first = await harness.run(await harness.open("I need help with an order."))
    book.canary = False
    await harness.world.add_message("tk_1", 2, TicketMessage(author="customer", body="Order #W1", created_at=NOW))
    second = await harness.run({"support_messages": [HumanMessage("Order #W1", id="tk_1#2")], "reply_position": 3})

    assert first.value["versions"] == second.value["versions"] == {"support": "support@2"}
    assert book.pins == [("support", "wi_1")]
    [system, *_] = harness.models.chat("support").calls[-1]  # pyright: ignore[reportAttributeAccessIssue]
    assert "Be brief." in system.text
    assert harness.runs[-1][0].turns == 2


async def test_each_turn_reports_every_agents_totals(store: LocalVectorStore) -> None:
    harness = Harness(store)
    harness.models.script("dispatcher", route("support"))
    harness.models.script("support", calls(("find_user_id_by_email", {"email": "ada@example.com"})), reply("Hi Ada."))
    await harness.run(await harness.open("Hello, it's ada@example.com", owner=None))

    [runs] = harness.runs
    by_agent = {run.agent: run for run in runs}
    assert set(by_agent) == {"dispatcher", "support"}
    assert (by_agent["dispatcher"].outcome, by_agent["dispatcher"].model_calls) == ("routed", 1)
    support = by_agent["support"]
    assert (support.version_id, support.outcome, support.turns) == ("support@1", "waiting_customer", 1)
    assert (support.model_calls, support.tool_calls, support.input_tokens, support.output_tokens) == (2, 1, 200, 40)
    assert not support.finished


async def test_a_paused_agent_hands_its_customer_to_a_person(store: LocalVectorStore) -> None:
    limits = Switches()
    limits.paused_agents.add("support")
    harness = Harness(store, limits=limits)
    output = await harness.run(await harness.open("Where is my order?"))

    assert (output.value["disposition"], output.value["stop_reason"]) == ("escalated", "paused")
    assert output.value["outputs"]["support"]["reply"] == HANDOFF_REPLY
    [runs] = harness.runs
    assert (runs[0].outcome, runs[0].stop_reason, runs[0].model_calls) == ("escalated", "paused", 0)


async def test_an_agent_out_of_budget_stops_and_a_person_takes_over(store: LocalVectorStore) -> None:
    limits = Switches()
    limits.spent.add("support")
    harness = Harness(store, limits=limits)
    output = await harness.run(await harness.open("Where is my order?"))
    assert output.value["stop_reason"] == "daily_budget"


async def test_calls_go_to_the_fallback_model_while_a_breaker_is_open(store: LocalVectorStore) -> None:
    limits = Switches()
    limits.fallback["fake"] = "gpt-6-luna"
    harness = Harness(store, limits=limits)
    harness.models.script("support", reply("Hi."))
    await harness.run(await harness.open("Hello"))

    called = next(e for e in await harness.events.read_after(0, limit=100) if e.kind is EventKind.MODEL_CALLED)
    assert called.payload["model"] == "gpt-6-luna"
    assert limits.calls == [("support", "gpt-6-luna", True)]


async def test_work_routed_to_a_paused_agent_goes_to_a_person(store: LocalVectorStore) -> None:
    limits = Switches()
    limits.paused_agents.add("support")
    harness = Harness(store, limits=limits)
    harness.models.script("dispatcher", route("support"))
    output = await harness.run(await harness.open("Where is my order?", owner=None))

    assert output.value["owner"] == "human"
    assert output.value["route"]["reason"].startswith("support is paused, so a person takes the work.")


async def test_a_paused_dispatcher_sends_work_to_its_default_owner(store: LocalVectorStore) -> None:
    limits = Switches()
    limits.paused_agents.add("dispatcher")
    harness = Harness(store, limits=limits)
    harness.models.script("support", reply("Hello."))
    output = await harness.run(await harness.open("Where is my order?", owner=None))

    assert output.value["owner"] == "support"
    assert output.value["route"]["reason"] == "The Dispatcher is paused, so the work went to its default owner."
    assert harness.models.chat("dispatcher").calls == []  # pyright: ignore[reportAttributeAccessIssue]
