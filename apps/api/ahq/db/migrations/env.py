from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from ahq.db.engine import sqlalchemy_url
from ahq.db.models import Base
from ahq.db.models.ops import Xid8
from ahq.settings import get_settings

ischema_names["xid8"] = Xid8
MANAGED_SCHEMAS = {table.schema for table in Base.metadata.tables.values()}


def _include_name(name: str | None, type_: str, parent_names: object) -> bool:
    if type_ == "schema":
        return name in MANAGED_SCHEMAS
    return True


def _url() -> str:
    url = context.config.attributes.get("url")
    if url:
        return str(url)
    settings = get_settings()
    configured = settings.database_url_unpooled or settings.database_url
    if configured is None:
        raise RuntimeError("set DATABASE_URL_UNPOOLED (or DATABASE_URL) to run migrations")
    return configured.get_secret_value()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_schemas=True,
        include_name=_include_name,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(sqlalchemy_url(_url()), connect_args={"prepare_threshold": None})
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=sqlalchemy_url(_url()), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
