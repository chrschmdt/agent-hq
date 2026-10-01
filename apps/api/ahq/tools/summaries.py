from __future__ import annotations

import json
from typing import Any, cast

from pydantic import JsonValue

from ahq.domain import ToolResult

SCALARS = ("status", "order_id", "user_id", "product_id", "name", "draft_id", "incident_id")
TEXT_LIMIT = 120
ROWS_KEYS = ("rows", "results", "tickets", "clusters", "items")


def summarize_result(tool: str, result: ToolResult) -> dict[str, JsonValue]:
    if not result.ok:
        return {}
    try:
        data: Any = json.loads(result.output)
    except ValueError:
        return {"text": _clip(result.output)}
    if isinstance(data, list):
        items = cast("list[Any]", data)
        if tool.startswith("knowledge_"):
            records = [cast("dict[str, Any]", item) for item in items if isinstance(item, dict)]
            return {"passages": [str(record["id"]) for record in records if "id" in record]}
        return {"rows": len(items)}
    if isinstance(data, dict):
        return _record(cast("dict[str, Any]", data))
    return {"text": _clip(str(data))}


def _record(data: dict[str, Any]) -> dict[str, JsonValue]:
    summary: dict[str, JsonValue] = {}
    for key in SCALARS:
        value = data.get(key)
        if isinstance(value, str | int | float | bool):
            summary[key] = value
    for key in ROWS_KEYS:
        value = data.get(key)
        if isinstance(value, list | dict):
            summary[key] = len(cast("list[Any] | dict[str, Any]", value))
    return summary or {"fields": len(data)}


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= TEXT_LIMIT else text[: TEXT_LIMIT - 3] + "..."
