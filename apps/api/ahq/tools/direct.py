from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ahq.domain import NotFoundError, ToolResult
from ahq.tools.executor import ToolExecutor
from ahq.tools.types import Principal


class DirectToolProvider:
    def __init__(self, executor: ToolExecutor, principals: Mapping[str, Principal]) -> None:
        self._executor = executor
        self._principals = dict(principals)

    async def call(self, subject: str, server: str, tool: str, arguments: Mapping[str, Any]) -> ToolResult:
        principal = self._principals.get(subject)
        if principal is None:
            raise NotFoundError(f"no principal {subject!r}")
        return await self._executor.call(principal, tool, arguments)
