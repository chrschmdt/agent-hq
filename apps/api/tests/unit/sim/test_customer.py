from __future__ import annotations

import json
from datetime import UTC, datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ahq.domain.world import TicketMessage
from ahq.sim.customer import GREETING, CustomerSimulator, scenario
from ahq.testing import FakeChatModels

NOW = datetime(2026, 6, 15, tzinfo=UTC)


def test_a_scenario_is_laid_out_like_tau3s() -> None:
    text = scenario("Return a lamp.\nAnd a mug.", "You are Ada.", None, "Be polite.", persona="Curt.")
    assert text == (
        "Persona:\n\tCurt.\nInstructions:\n\tDomain: retail\n\tReason for call:\n\t\tReturn a lamp.\n\t\tAnd a mug."
        "\n\tKnown info:\n\t\tYou are Ada.\n\tTask instructions:\n\t\tBe polite."
    )


async def test_the_customer_sees_the_agent_as_its_counterpart_and_can_end_the_chat() -> None:
    models = FakeChatModels()
    model = models.script("customer", "All sorted, thanks! ###STOP###", json.dumps({"score": 4, "reason": "Fine."}))
    simulator = CustomerSimulator(models)
    transcript = [TicketMessage(author="agent", body=GREETING, created_at=NOW)]
    turn, _ = await simulator.next_turn("Instructions:\n\tDomain: retail", transcript)
    assert (turn.text, turn.ending) == ("All sorted, thanks!", "stop")
    system, greeting = model.calls[0]
    assert isinstance(system, SystemMessage)
    assert "###STOP###" in str(system.content)
    assert isinstance(greeting, HumanMessage)
    transcript.append(TicketMessage(author="customer", body="All sorted.", created_at=NOW))
    rating, _ = await simulator.rate("Instructions:\n\tDomain: retail", transcript)
    assert rating.score == 4
    assert isinstance(model.calls[1][2], AIMessage)


async def test_a_transfer_and_an_out_of_scope_end_differently() -> None:
    models = FakeChatModels()
    models.script("customer", "###TRANSFER###", "I don't know that. ###OUT-OF-SCOPE###")
    simulator = CustomerSimulator(models)
    first, _ = await simulator.next_turn("x", [])
    second, _ = await simulator.next_turn("x", [])
    assert (first.text, first.ending) == ("", "transfer")
    assert (second.text, second.ending) == ("I don't know that.", "out_of_scope")
