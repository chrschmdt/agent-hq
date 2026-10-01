from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import psycopg
import pytest

from ahq.adapters.clock import ManualClock
from ahq.db.migrate import upgrade
from ahq.domain.retail import RetailSnapshot
from ahq.retail import load_snapshot
from ahq.settings import REPO_ROOT, Settings

LOCAL_DB = "postgresql://ahq:ahq@localhost:5432/ahq_test"
LOCAL_POOLED_DB = "postgresql://ahq:ahq@localhost:6432/ahq_test"
OPS_TABLES = "ops.approvals, ops.work_items, ops.events, ops.sim_script, ops.sim_runs"
TAU3_DIR = REPO_ROOT / "data" / "tau3" / "v1.0.1"
LOCAL_QDRANT = "http://localhost:6333"


def make_settings(**values: Any) -> Settings:
    defaults: dict[str, Any] = {
        "model_profile": "mock",
        "queue_backend": "inprocess",
        "tool_transport": "asgi",
        "operator_token": "test-operator-token",
        "cron_secret": "test-cron-secret",
        "sse_max_seconds": 1.0,
        "sse_poll_seconds": 0.01,
    }
    return Settings(_env_file=None, **{**defaults, **values})  # pyright: ignore[reportCallIssue]


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    return make_settings


@pytest.fixture(scope="session")
def tau3_snapshot() -> RetailSnapshot:
    return load_snapshot(TAU3_DIR / "db.json")


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


def _reachable(url: str) -> bool:
    try:
        with psycopg.connect(url, connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


def _require_services() -> bool:
    return os.environ.get("AHQ_REQUIRE_SERVICES") == "1"


@pytest.fixture(scope="session")
def pg_url() -> str:
    url = os.environ.get("AHQ_TEST_DATABASE_URL", LOCAL_DB)
    if not _reachable(url):
        if _require_services():
            pytest.fail(f"Postgres is required but not reachable at {url}")
        pytest.skip("local Postgres is not running (make up)")
    with ThreadPoolExecutor(max_workers=1) as thread:
        thread.submit(upgrade, url).result()
    return url


@pytest.fixture(scope="session")
def pooled_pg_url(pg_url: str) -> str:
    url = os.environ.get("AHQ_TEST_POOLED_DATABASE_URL", LOCAL_POOLED_DB)
    if not _reachable(url):
        if _require_services():
            pytest.fail(f"PgBouncer is required but not reachable at {url}")
        pytest.skip("PgBouncer is not running (make up-pooled)")
    return url


@pytest.fixture
def clean_db(pg_url: str) -> str:
    with psycopg.connect(pg_url, autocommit=True) as connection:
        connection.execute(f"TRUNCATE {OPS_TABLES} RESTART IDENTITY CASCADE")
    return pg_url


@pytest.fixture(scope="session")
def qdrant_url() -> str:
    url = os.environ.get("AHQ_TEST_QDRANT_URL", LOCAL_QDRANT)
    try:
        httpx.get(url, timeout=2).raise_for_status()
    except httpx.HTTPError:
        if _require_services():
            pytest.fail(f"Qdrant is required but not reachable at {url}")
        pytest.skip("local Qdrant is not running (make up)")
    return url
