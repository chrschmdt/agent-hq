from __future__ import annotations

from typing import Any

from ahq.agents import SPECS
from ahq.config import load_world_config
from ahq.graphs import work_message

TODAY = load_world_config().anchor.date().isoformat()


def render(context: dict[str, Any]) -> dict[str, Any]:
    case = context["vars"]
    spec = SPECS[case["agent"]]
    values = {"today": TODAY, "now": f"{TODAY}T10:00:00-04:00", "ticket_id": "tk_check", "work_item_id": "wi_check"}
    system = spec.prompt.render(values).text
    message = work_message(case["kind"], case["message"]) if spec.name == "dispatcher" else case["message"]
    schema = spec.reply.model_json_schema()
    return {
        "prompt": [{"role": "system", "content": system}, {"role": "user", "content": message}],
        "config": {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": spec.reply.__name__, "schema": schema, "strict": True},
            }
        },
    }
