from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableBinding, RunnableSequence
from pydantic import SecretStr

from ahq.adapters.openrouter.chat import OpenRouterChatModels
from ahq.config import ModelCatalog, load_model_catalog
from ahq.domain import SupportTurn, SystemPrompt


def bound_kwargs(model: str, catalog: ModelCatalog | None = None) -> dict[str, Any]:
    models = OpenRouterChatModels(
        (catalog or load_model_catalog()).forcing({"support": model}),
        "medium",
        api_key=SecretStr("test-key"),
        base_url="https://openrouter.test/api",
    )
    runnable = models.agent_model(
        "support", system=SystemPrompt(stable="Rules.", dynamic="Now."), tools=[], reply=SupportTurn
    )
    assert isinstance(runnable, RunnableSequence)
    binding = runnable.last
    assert isinstance(binding, RunnableBinding)
    return dict(binding.kwargs)


def test_a_reasoning_model_thinks_and_returns_a_summary() -> None:
    kwargs = bound_kwargs("claude-opus-5-5")
    assert kwargs["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


def test_a_model_that_replies_from_the_prompt_gets_no_schema() -> None:
    kwargs = bound_kwargs("claude-sonnet-5-5")
    assert kwargs["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert kwargs["output_config"] == {"effort": "medium"}


def test_a_model_without_reasoning_is_bound_as_before() -> None:
    kwargs = bound_kwargs("claude-haiku-4-5")
    assert "thinking" not in kwargs
    assert "output_config" in kwargs


def test_an_effort_in_the_catalog_goes_beside_the_reply_format() -> None:
    catalog = load_model_catalog()
    assert "effort" not in bound_kwargs("claude-opus-5-5")["output_config"]
    tuned = catalog.models["claude-opus-5-5"].model_copy(update={"effort": "high"})
    catalog = catalog.model_copy(update={"models": {**catalog.models, "claude-opus-5-5": tuned}})
    config = bound_kwargs("claude-opus-5-5", catalog)["output_config"]
    assert (config["effort"], config["format"]["type"]) == ("high", "json_schema")
