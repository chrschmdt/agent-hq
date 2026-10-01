from __future__ import annotations

import pytest

from ahq.settings import Settings

pytestmark = pytest.mark.live


@pytest.fixture(scope="session")
def live_settings() -> Settings:
    return Settings()


@pytest.fixture(autouse=True)
def _allow_network(socket_enabled: None) -> None: ...
def require(value: object, name: str) -> None:
    if value is None:
        pytest.skip(f"{name} is not set")
