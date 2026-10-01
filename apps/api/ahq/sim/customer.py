from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from textwrap import indent
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import Field

from ahq.domain import CallReport, StrictModel
from ahq.domain.sim import CustomerBrief
from ahq.domain.world import TicketMessage
from ahq.ports import ChatModels, ask_typed

GUIDELINES = Path(__file__).with_name("customer_guidelines.md").read_text().strip()
GREETING = "Hi! How can I help you today?"
TAB = "\t"
PATIENCE = (
    "Only end the conversation once the agent has confirmed that everything you asked for is done, or has told you "
    "it cannot be done. Agreeing to a proposal is not the end: wait for the agent to carry it out."
)
RATING = (
    "The conversation is over. As the customer you played, rate the support you received from 1 (very poor) to 5 "
    "(excellent), with one sentence on why."
)

Ending = Literal["stop", "transfer", "out_of_scope"]
ENDINGS: dict[str, Ending] = {"###STOP###": "stop", "###TRANSFER###": "transfer", "###OUT-OF-SCOPE###": "out_of_scope"}


class CustomerTurn(StrictModel):
    text: str
    ending: Ending | None = None


class Rating(StrictModel):
    """The customer's end-of-chat rating."""

    score: int = Field(ge=1, le=5, description="1 is very poor, 5 is excellent.")
    reason: str = Field(description="One sentence on why.")


def scenario(
    reason_for_call: str,
    known_info: str | None,
    unknown_info: str | None,
    task_instructions: str,
    *,
    persona: str | None = None,
) -> str:
    parts = ["Domain: retail", f"Reason for call:\n{indent(reason_for_call, TAB)}"]
    if known_info:
        parts.append(f"Known info:\n{indent(known_info, TAB)}")
    if unknown_info:
        parts.append(f"Unknown info:\n{indent(unknown_info, TAB)}")
    parts.append(f"Task instructions:\n{indent(task_instructions, TAB)}")
    lines = ["Persona:", indent(persona, TAB)] if persona else []
    lines += ["Instructions:", indent("\n".join(parts), TAB)]
    return "\n".join(lines)


def brief_scenario(brief: CustomerBrief) -> str:
    return scenario(brief.reason_for_call, brief.known_info, brief.unknown_info, brief.task_instructions)


class CustomerSimulator:
    def __init__(self, models: ChatModels) -> None:
        self._models = models

    async def next_turn(
        self, instructions: str, transcript: Sequence[TicketMessage]
    ) -> tuple[CustomerTurn, CallReport]:
        model = self._models.chat("customer")
        reply = await model.ainvoke([self._system(instructions), *_as_customer_sees_it(transcript)])
        text = reply.text.strip()
        ending: Ending | None = None
        for token, name in ENDINGS.items():
            if token in text:
                ending = ending or name
                text = text.replace(token, "").strip()
        return CustomerTurn(text=text, ending=ending), self._models.report(reply)

    async def rate(self, instructions: str, transcript: Sequence[TicketMessage]) -> tuple[Rating, CallReport]:
        messages = [self._system(instructions), *_as_customer_sees_it(transcript), HumanMessage(RATING)]
        return await ask_typed(self._models, "customer", Rating, messages)

    def _system(self, instructions: str) -> SystemMessage:
        return SystemMessage(f"{GUIDELINES}\n{PATIENCE}\n\n<scenario>\n{instructions}\n</scenario>")


def _as_customer_sees_it(transcript: Sequence[TicketMessage]) -> list[BaseMessage]:
    return [
        AIMessage(message.body) if message.author == "customer" else HumanMessage(message.body)
        for message in transcript
        if message.author != "system"
    ]
