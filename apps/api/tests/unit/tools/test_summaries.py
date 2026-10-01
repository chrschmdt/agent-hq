from __future__ import annotations

import json

from ahq.domain import ToolResult
from ahq.tools import summarize_result


def test_a_search_is_summarized_by_the_passages_it_found() -> None:
    passages = [{"id": "policy-returns@v1#2", "text": "..."}, {"id": "help-returns@v3#1", "text": "..."}]
    result = ToolResult(output=json.dumps(passages))
    assert summarize_result("knowledge_search", result) == {"passages": ["policy-returns@v1#2", "help-returns@v3#1"]}


def test_a_list_is_counted_and_a_record_keeps_a_few_telling_fields() -> None:
    assert summarize_result("analytics_similar_tickets", ToolResult(output=json.dumps([1, 2, 3]))) == {"rows": 3}
    order = {"order_id": "#W1", "status": "delivered", "items": [{}, {}], "address": {"city": "Austin"}}
    assert summarize_result("get_order_details", ToolResult(output=json.dumps(order))) == {
        "status": "delivered",
        "order_id": "#W1",
        "items": 2,
    }
    assert summarize_result("x", ToolResult(output=json.dumps({"a": {"b": 1}}))) == {"fields": 1}


def test_plain_answers_are_clipped_and_failures_say_nothing() -> None:
    assert summarize_result("find_user_id_by_email", ToolResult(output="ada_1")) == {"text": "ada_1"}
    long = summarize_result("calculate", ToolResult(output="word " * 100))["text"]
    assert isinstance(long, str)
    assert len(long) == 120
    assert long.endswith("...")
    assert summarize_result("get_order_details", ToolResult.error("Order not found")) == {}
