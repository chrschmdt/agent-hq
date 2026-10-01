from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

_SCHEMES = ("postgres://", "postgresql://", "postgresql+psycopg://")


def sqlalchemy_url(url: str) -> str:
    if not url.startswith(_SCHEMES):
        raise ValueError("expected a postgres:// or postgresql:// URL")
    parts = urlsplit(url)
    return urlunsplit(parts._replace(scheme="postgresql+psycopg"))


def libpq_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(scheme="postgresql"))


def make_engine(url: str, *, pool_size: int = 5) -> AsyncEngine:
    return create_async_engine(
        sqlalchemy_url(url),
        pool_size=pool_size,
        max_overflow=pool_size,
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None},
    )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
