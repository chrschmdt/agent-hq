from __future__ import annotations

import secrets

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from ahq.adapters.openrouter import OpenRouterChatModels, OpenRouterEmbedder, OpenRouterReranker
from ahq.config import load_model_catalog
from ahq.domain import StrictModel
from ahq.settings import Settings
from tests.live.conftest import require

pytestmark = [pytest.mark.live, pytest.mark.asyncio(loop_scope="session")]

POLICY_LINE = (
    "Returns are accepted within 30 days of delivery for unused items in their original packaging; "
    "refunds go back to the original payment method within five business days. "
)


class Verdict(StrictModel):
    route: str
    confident: bool


@tool
def echo(text: str) -> str:
    """Return the given text unchanged."""
    return text


def models(settings: Settings, profile: str = "medium") -> OpenRouterChatModels:
    require(settings.openrouter_api_key, "OPENROUTER_API_KEY")
    assert settings.openrouter_api_key is not None
    return OpenRouterChatModels(
        load_model_catalog(),
        profile,  # pyright: ignore[reportArgumentType]
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )


async def test_claude_answers_through_the_anthropic_endpoint(live_settings: Settings) -> None:
    chat = models(live_settings)
    reply = await chat.chat("smoke").ainvoke([HumanMessage("Reply with the single word: ready")])
    assert "ready" in str(reply.content).lower()
    assert chat.report(reply).usage.output_tokens > 0


async def test_claude_prompt_caching_hits_on_the_second_call(live_settings: Settings) -> None:
    chat = models(live_settings)
    model = chat.chat("support")
    nonce = f"Policy revision {secrets.token_hex(6)}. "
    system = SystemMessage(
        content=[{"type": "text", "text": nonce + POLICY_LINE * 180, "cache_control": {"type": "ephemeral"}}]
    )
    first = await model.ainvoke([system, HumanMessage("How long is the return window?")])
    second = await model.ainvoke([system, HumanMessage("Where do refunds go?")])
    first_call, second_call = chat.report(first), chat.report(second)
    assert second_call.usage.cache_read_tokens > 0.9 * first_call.usage.input_tokens, (first_call, second_call)
    assert second_call.billed_usd is not None
    assert first_call.billed_usd is not None
    assert second_call.billed_usd < first_call.billed_usd


async def test_claude_native_structured_output(live_settings: Settings) -> None:
    model = models(live_settings).chat("dispatcher")
    typed = model.with_structured_output(Verdict, method="json_schema")
    answer = await typed.ainvoke("A customer asks where their parcel is. Route to 'support' and say if you are sure.")
    assert isinstance(answer, Verdict)
    assert answer.route == "support"


async def test_claude_calls_tools(live_settings: Settings) -> None:
    model = models(live_settings).chat("support").bind_tools([echo])
    reply = await model.ainvoke("Use the echo tool to echo the word 'pong'.")
    assert isinstance(reply, AIMessage)
    assert reply.tool_calls
    assert reply.tool_calls[0]["name"] == "echo"


async def test_claude_accepts_tools_and_structured_output_together(live_settings: Settings) -> None:
    model = models(live_settings).chat("support")
    schema = {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    }
    bound = model.bind_tools([echo]).bind(output_config={"format": schema})
    reply = await bound.ainvoke("Say hello. Do not use any tools.")
    assert isinstance(reply, AIMessage)


async def test_adaptive_thinking_and_effort_on_sonnet(live_settings: Settings) -> None:
    require(live_settings.openrouter_api_key, "OPENROUTER_API_KEY")
    assert live_settings.openrouter_api_key is not None
    key = live_settings.openrouter_api_key
    model = ChatAnthropic(
        model_name="anthropic/claude-sonnet-5.5",
        base_url=live_settings.openrouter_base_url,
        api_key=key,
        default_headers={"Authorization": f"Bearer {key.get_secret_value()}"},
        max_tokens_to_sample=2048,
        thinking={"type": "adaptive"},
        timeout=None,
        stop=None,
    )
    reply = await model.ainvoke("What is 17 * 23? Answer with the number.", output_config={"effort": "low"})
    assert "391" in str(reply.content)


@pytest.mark.parametrize("role", ["qa", "customer"])
async def test_openai_family_models_give_typed_output(live_settings: Settings, role: str) -> None:
    model = models(live_settings, "high").chat(role)  # pyright: ignore[reportArgumentType]
    answer = await model.with_structured_output(Verdict, method="json_schema").ainvoke(
        "Route a shipping question to 'support'. Are you confident?"
    )
    assert isinstance(answer, Verdict)


async def test_embeddings_have_the_configured_dimensions(live_settings: Settings) -> None:
    require(live_settings.openrouter_api_key, "OPENROUTER_API_KEY")
    assert live_settings.openrouter_api_key is not None
    embedder = OpenRouterEmbedder(
        load_model_catalog().embeddings,
        api_key=live_settings.openrouter_api_key,
        base_url=live_settings.openrouter_base_url,
    )
    try:
        documents = await embedder.embed(["Returns within 30 days.", "Parcel delayed by the carrier."], "document")
        (query,) = await embedder.embed(["How long do I have to return an item?"], "query")
    finally:
        await embedder.aclose()
    assert len(documents) == 2
    assert {len(vector) for vector in [*documents, query]} == {1024}


async def test_the_reranker_puts_the_relevant_document_first(live_settings: Settings) -> None:
    require(live_settings.openrouter_api_key, "OPENROUTER_API_KEY")
    assert live_settings.openrouter_api_key is not None
    reranker = OpenRouterReranker(
        load_model_catalog().rerank,
        api_key=live_settings.openrouter_api_key,
        base_url=live_settings.openrouter_base_url,
    )
    documents = ["Our store opens at 9am.", "Items can be returned within 30 days of delivery.", "We ship with UPS."]
    try:
        hits = await reranker.rerank("What is the return window?", documents, top_n=2)
    finally:
        await reranker.aclose()
    assert hits[0].index == 1
    assert len(hits) == 2
