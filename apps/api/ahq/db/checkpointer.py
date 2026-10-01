from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from ahq.db.engine import libpq_url

CONNECTION_KWARGS = {"autocommit": True, "prepare_threshold": None, "row_factory": dict_row}


@asynccontextmanager
async def open_checkpointer(url: str, *, max_size: int = 5) -> AsyncIterator[AsyncPostgresSaver]:
    pool: AsyncConnectionPool[AsyncConnection[DictRow]] = AsyncConnectionPool(
        libpq_url(url),
        connection_class=AsyncConnection[DictRow],
        min_size=0,
        max_size=max_size,
        kwargs=CONNECTION_KWARGS,
        open=False,
    )
    await pool.open()
    try:
        yield AsyncPostgresSaver(pool)
    finally:
        await pool.close()


async def setup_checkpointer(direct_url: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(libpq_url(direct_url)) as saver:
        await saver.setup()
