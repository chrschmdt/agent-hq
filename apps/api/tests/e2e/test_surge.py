from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel

from ahq.config import ModelRole
from ahq.domain import RetryLater, SystemPrompt
from ahq.evals.scenarios import check_scenario
from ahq.testing.rules import RuleChatModels
from tests.conftest import make_settings


class ProviderError(Exception):
    pass


class BusyProvider(RuleChatModels):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def agent_model(
        self,
        role: ModelRole,
        *,
        system: SystemPrompt,
        tools: Sequence[Mapping[str, Any]],
        reply: type[BaseModel],
        model: str | None = None,
    ) -> Runnable[Sequence[BaseMessage], BaseMessage]:
        runnable = super().agent_model(role, system=system, tools=tools, reply=reply, model=model)

        async def call(messages: Sequence[BaseMessage]) -> BaseMessage:
            self.calls += 1
            if self.calls % 3 == 0:
                raise ProviderError("connection error") from RetryLater(4.0, "the provider answered 429")
            return await runnable.ainvoke(messages)

        return RunnableLambda(call)


async def test_a_surge_answers_every_customer_even_when_the_provider_pushes_back() -> None:
    models = BusyProvider()
    report = await check_scenario(
        make_settings(tool_transport="direct"), "surge", seed=7, trials=1, max_usd=0.1, models=models
    )
    [trial] = report.trials
    assert trial.error is None
    assert trial.passed, trial.expectations
    answered = trial.expectations[0]
    assert answered.name == "every customer answered"
    assert answered.detail.startswith("60 of 60 answered")
    deferred = re.search(r"(\d+) deferrals", answered.detail)
    assert deferred is not None
    assert int(deferred[1]) > 0
    assert models.calls > 60
