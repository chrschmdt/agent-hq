from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field

from ahq.domain import CallReport, StrictModel
from ahq.domain.world import TicketMessage
from ahq.ports import ChatModels, ask_typed

SYSTEM = """You will be given a list of expected outcomes and a conversation that was collected during a test case
run. The conversation is between an agent and a customer. Your job is to evaluate whether the agent satisfies each of
the expected outcomes. Grade each expected outcome individually: write a short reasoning first, then whether the agent
met it."""


class AssertionVerdict(StrictModel):
    """The judge's verdict on one expected outcome, reasoning first."""

    expected_outcome: str = Field(description="The expected outcome being graded, repeated from the input.")
    reasoning: str = Field(description="A short explanation.")
    met: bool = Field(description="Whether the agent satisfied the expected outcome.")


class AssertionVerdicts(StrictModel):
    """Verdicts for every expected outcome."""

    results: list[AssertionVerdict]


def transcript_text(messages: Sequence[TicketMessage]) -> str:
    roles = {"customer": "user", "agent": "assistant", "system": "system"}
    return "\n".join(f"{roles[message.author]}: {message.body}" for message in messages)


async def judge_assertions(
    models: ChatModels, assertions: Sequence[str], transcript: Sequence[TicketMessage]
) -> tuple[list[AssertionVerdict], CallReport | None]:
    if not assertions:
        return [], None
    prompt = f"conversation:\n{transcript_text(transcript)}\n\nexpectedOutcomes:\n{list(assertions)}"
    verdicts, report = await ask_typed(models, "qa", AssertionVerdicts, [SystemMessage(SYSTEM), HumanMessage(prompt)])
    return verdicts.results, report
