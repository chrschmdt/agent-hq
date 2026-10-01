from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import JsonValue

from ahq.domain.base import StrictModel

ERROR_PREFIX = "Error: "


class Effect(StrEnum):
    READ = "read"
    WRITE = "write"
    DRAFT = "draft"
    GENERIC = "generic"


class ToolResult(StrictModel):
    output: str

    @property
    def ok(self) -> bool:
        return not self.output.startswith(ERROR_PREFIX)

    @classmethod
    def error(cls, message: str) -> ToolResult:
        return cls(output=f"{ERROR_PREFIX}{message}")


class ToolCallRecord(StrictModel):
    key: str
    work_item_id: str | None
    subject: str
    tool: str
    arguments: dict[str, JsonValue]
    output: str
    approval_id: str | None = None
    recorded_at: datetime
