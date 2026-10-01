from __future__ import annotations

import pytest

from tests.conftest import make_settings


def test_production_calls_itself_at_its_public_address() -> None:
    settings = make_settings(
        environment="production",
        site_url="https://agent-hq.example/",
        vercel_production_url="ahq-abc.vercel.app",
        vercel_url="ahq-abc-123.vercel.app",
    )
    assert settings.self_url == "https://agent-hq.example"


def test_without_a_public_address_production_uses_the_domain_vercel_names() -> None:
    settings = make_settings(
        environment="production", vercel_production_url="ahq-abc.vercel.app", vercel_url="ahq-abc-123.vercel.app"
    )
    assert settings.self_url == "https://ahq-abc.vercel.app"


def test_a_preview_calls_its_own_deployment_and_local_calls_localhost() -> None:
    preview = make_settings(
        environment="preview", site_url="https://agent-hq.example", vercel_url="ahq-abc-123.vercel.app"
    )
    assert preview.self_url == "https://ahq-abc-123.vercel.app"
    assert make_settings().self_url == "http://localhost:8000"


def test_a_deployment_needs_the_mcp_secret_whatever_ahq_env_says() -> None:
    stray = make_settings(environment="local", vercel_url="ahq-abc-123.vercel.app")
    assert stray.is_deployed
    with pytest.raises(RuntimeError, match="AHQ_MCP_TOKEN_SECRET"):
        _ = stray.context_key
    configured = make_settings(environment="local", vercel_url="ahq-abc-123.vercel.app", mcp_token_secret="secret")
    assert configured.context_key != make_settings().context_key
    assert not make_settings().is_deployed
