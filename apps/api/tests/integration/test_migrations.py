from __future__ import annotations

from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql.base import ischema_names

from ahq.db.engine import sqlalchemy_url
from ahq.db.models import Base
from ahq.db.models.ops import Xid8

pytestmark = pytest.mark.db

ischema_names["xid8"] = Xid8
SCHEMAS = {table.schema for table in Base.metadata.tables.values()}


def _ours(name: str | None, type_: str, parent_names: Any) -> bool:
    return name in SCHEMAS if type_ == "schema" else True


def test_migrations_match_the_models(pg_url: str) -> None:
    engine = create_engine(sqlalchemy_url(pg_url))
    with engine.connect() as connection:
        options: dict[str, Any] = {"include_schemas": True, "include_name": _ours, "compare_type": True}
        differences = compare_metadata(MigrationContext.configure(connection, opts=options), Base.metadata)
    engine.dispose()
    assert differences == []
