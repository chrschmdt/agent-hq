from __future__ import annotations

import json

from ahq.guardrails import redact


def test_personal_fields_of_a_tool_result_are_redacted() -> None:
    result = json.dumps(
        {
            "user_id": "ada_lovelace_1815",
            "name": {"first_name": "Ada", "last_name": "Lovelace"},
            "address": {"address1": "12 Marsh Lane", "address2": "Suite 4", "city": "Austin", "zip": "78701"},
            "email": "ada@example.com",
            "orders": ["#W1234567"],
        }
    )
    redacted = json.loads(redact(result))
    assert redacted["user_id"] == "[customer]"
    assert redacted["name"] == {"first_name": "[redacted]", "last_name": "[redacted]"}
    assert redacted["address"]["address1"] == "[redacted]"
    assert redacted["address"]["zip"] == "[redacted]"
    assert redacted["address"]["city"] == "Austin"
    assert redacted["email"] == "[redacted]"
    assert redacted["orders"] == ["#W1234567"]


def test_personal_data_in_free_text_is_redacted() -> None:
    text = "Hi, I'm at 445 Maple Drive now; write to ada.l+shop@example.co.uk about #W1234567."
    assert redact(text) == "Hi, I'm at [address] now; write to [email] about #W1234567."


def test_text_without_personal_data_is_unchanged() -> None:
    text = "Returns are accepted within 30 days of delivery; the refund goes to the original payment method."
    assert redact(text) == text
