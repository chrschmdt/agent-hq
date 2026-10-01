from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import JsonValue

from ahq.domain import AhqError, StrictModel


class QueryRows(StrictModel):
    columns: list[str]
    rows: list[list[JsonValue]]


class AnalyticsError(AhqError):
    pass


class ReadOnlySql(Protocol):
    async def fetch(self, sql: str, params: Mapping[str, Any] | None = None) -> QueryRows: ...
