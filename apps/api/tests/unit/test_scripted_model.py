from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from ahq.domain import StrictModel
from ahq.testing import FakeChatModels, ScriptedChatModel


class Answer(StrictModel):
    value: int


def test_replies_in_order_then_repeats_the_last() -> None:
    model = ScriptedChatModel(replies=["one", "two"])
    assert [model.invoke("x").content for _ in range(3)] == ["one", "two", "two"]
    assert len(model.calls) == 3


def test_replies_can_depend_on_the_messages() -> None:
    model = ScriptedChatModel(replies=[lambda messages: f"you said {messages[-1].content}"])
    assert model.invoke([HumanMessage("hello")]).content == "you said hello"


def test_scripted_messages_keep_their_tool_calls() -> None:
    call = AIMessage(content="", tool_calls=[{"name": "echo", "args": {"text": "hi"}, "id": "call_1"}])
    reply = ScriptedChatModel(replies=[call]).invoke("x")
    assert isinstance(reply, AIMessage)
    assert reply.tool_calls[0]["name"] == "echo"


def test_structured_output_requires_native_json_schema() -> None:
    model = ScriptedChatModel(replies=['{"value": 3}'])
    assert model.with_structured_output(Answer, method="json_schema").invoke("x") == Answer(value=3)
    with pytest.raises(AssertionError, match="json_schema"):
        model.with_structured_output(Answer)


def test_forced_tool_choice_is_rejected() -> None:
    with pytest.raises(AssertionError, match="forced tool choice"):
        ScriptedChatModel(replies=["x"]).bind_tools([], tool_choice="any")


def test_fake_models_report_usage_and_cost_nothing() -> None:
    models = FakeChatModels()
    report = models.report(models.chat("support").invoke("x"))
    assert report.usage.input_tokens > 0
    assert report.cost_usd(models.price("support")) == 0
