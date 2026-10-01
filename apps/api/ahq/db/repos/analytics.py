from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ahq.ports import AnalyticsError, QueryRows

ROLE = "ahq_analytics_ro"


class PgReadOnlySql:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, timeout_ms: int = 5000) -> None:
        self._sessions = sessions
        self._timeout_ms = timeout_ms

    async def fetch(self, sql: str, params: Mapping[str, Any] | None = None) -> QueryRows:
        async with self._sessions() as session, session.begin():
            await session.execute(text(f"SET LOCAL ROLE {ROLE}"))
            await session.execute(text("SET LOCAL transaction_read_only = on"))
            await session.execute(text(f"SET LOCAL statement_timeout = {int(self._timeout_ms)}"))
            await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            try:
                if params is None:
                    connection = await session.connection()
                    result = await connection.exec_driver_sql(sql.replace("%", "%%"))
                else:
                    result = await session.execute(text(sql), dict(params))
            except DBAPIError as error:
                raise AnalyticsError(_message(error, self._timeout_ms)) from error
            columns = list(result.keys())
            rows = [[_json(value) for value in row] for row in result.fetchall()]
        return QueryRows(columns=columns, rows=rows)


def _message(error: DBAPIError, timeout_ms: int) -> str:
    diag = getattr(error.orig, "diag", None)
    primary = getattr(diag, "message_primary", None) or str(error.orig).splitlines()[0]
    if "statement timeout" in primary:
        return f"The query took longer than {timeout_ms / 1000:g} seconds; narrow it or add filters."
    return primary


def _json(value: Any) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    return str(value)
