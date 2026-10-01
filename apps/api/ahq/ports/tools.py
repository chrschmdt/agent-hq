from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ahq.domain import ToolResult


class ToolProvider(Protocol):
    async def call(self, subject: str, server: str, tool: str, arguments: Mapping[str, Any]) -> ToolResult: ...
