from __future__ import annotations

import pytest

from reportify.core.config import Settings
from reportify.modules.mcp.runtime import MCPRuntime
from reportify.modules.mcp.schemas import GrantRequest, MCPServerCreate
from reportify.modules.security.secrets import SecretService
from reportify.modules.tools.registry import ToolRegistry
from tests.integration.fake_mcp import closed_port_url
from tests.integration.mcp_helpers import expected_model_name, unique_slug


@pytest.fixture
async def registry(session_factory):
    tool_registry = ToolRegistry(session_factory)
    await tool_registry.sync_builtins()
    return tool_registry


@pytest.fixture
def mcp_runtime(session_factory, secret_service: SecretService) -> MCPRuntime:
    return MCPRuntime(
        session_factory,
        secret_service,
        allow_loopback=True,
        connect_timeout=5.0,
        read_timeout=5.0,
        probe_timeout=5.0,
    )


async def _prepare(mcp_hub, fake_mcp, *, grant: str | None = None) -> tuple[str, object]:
    slug = unique_slug()
    server = await mcp_hub.create(
        MCPServerCreate(name=f"MCP {slug}", slug=slug, url=fake_mcp.url)
    )
    await mcp_hub.discover(server.id)
    if grant is not None:
        tools = await mcp_hub.list_tools(server.id)
        tool = next(item for item in tools if item.model_name == expected_model_name(slug, grant))
        await mcp_hub.set_grant(
            tool.id,
            GrantRequest(allowed=True, risk_level="read", risk_acknowledged=True),
        )
    return slug, server


async def test_unauthorized_mcp_tools_are_hidden(registry, mcp_hub, fake_mcp) -> None:
    slug, _server = await _prepare(mcp_hub, fake_mcp)
    specs = await registry.list_for_run(task_id=None, conversation_id=None)

    assert not any(spec.source_slug == slug for spec in specs)
    decision = await registry.authorize(
        expected_model_name(slug, "echo"),
        task_id=None,
        conversation_id=None,
    )
    assert decision.allowed is False
    assert decision.reason == "denied"


async def test_granted_mcp_tool_becomes_visible_and_authorized(
    registry,
    mcp_hub,
    fake_mcp,
) -> None:
    slug, _server = await _prepare(mcp_hub, fake_mcp, grant="echo")
    specs = await registry.list_for_run(task_id=None, conversation_id=None)

    mcp_specs = [spec for spec in specs if spec.source_slug == slug]
    assert len(mcp_specs) == 1
    assert mcp_specs[0].model_name == expected_model_name(slug, "echo")
    assert mcp_specs[0].source_slug == slug

    decision = await registry.authorize(
        expected_model_name(slug, "echo"),
        task_id=None,
        conversation_id=None,
    )
    assert decision.allowed is True
    assert decision.reason == "granted"


async def test_revoked_mcp_tool_disappears(registry, mcp_hub, fake_mcp) -> None:
    slug, server = await _prepare(mcp_hub, fake_mcp, grant="echo")
    tools = await mcp_hub.list_tools(server.id)
    tool = next(item for item in tools if item.model_name == expected_model_name(slug, "echo"))
    await mcp_hub.revoke_grant(tool.id)

    specs = await registry.list_for_run(task_id=None, conversation_id=None)
    assert not any(spec.source_slug == slug for spec in specs)


async def test_mcp_runtime_builds_filtered_toolset(
    registry,
    mcp_runtime,
    mcp_hub,
    fake_mcp,
) -> None:
    slug, _server = await _prepare(mcp_hub, fake_mcp, grant="echo")
    specs = await registry.list_for_run(task_id=None, conversation_id=None)

    bundle = await mcp_runtime.toolsets(specs)
    assert slug in bundle.attached
    assert slug not in bundle.unavailable


async def test_unreachable_server_is_reported_not_fatal(
    registry,
    mcp_runtime,
    mcp_hub,
    fake_mcp,
) -> None:
    slug, _server = await _prepare(mcp_hub, fake_mcp, grant="echo")
    specs = await registry.list_for_run(task_id=None, conversation_id=None)
    fake_mcp.stop()

    bundle = await mcp_runtime.toolsets(specs)
    assert slug in bundle.unavailable
    assert slug not in bundle.attached


async def test_disabled_server_tools_are_skipped(
    registry,
    mcp_runtime,
    mcp_hub,
    fake_mcp,
) -> None:
    slug, server = await _prepare(mcp_hub, fake_mcp, grant="echo")
    specs = await registry.list_for_run(task_id=None, conversation_id=None)
    await mcp_hub.disable(server.id)

    fresh = await registry.list_for_run(task_id=None, conversation_id=None)
    assert not any(spec.source_slug == slug for spec in fresh)
    bundle = await mcp_runtime.toolsets(specs)
    assert slug in bundle.skipped


async def test_closed_port_server_never_reaches_run(mcp_hub) -> None:
    slug = unique_slug()
    server = await mcp_hub.create(
        MCPServerCreate(name=f"MCP {slug}", slug=slug, url=closed_port_url())
    )
    tested = await mcp_hub.test(server.id)
    assert tested.ok is False
    assert tested.status == "error"


def test_settings_allow_loopback_defaults_by_env() -> None:
    dev = Settings(_env_file=None, database_url="postgresql+asyncpg://x/y", secret_key="k")
    assert dev.allow_loopback is True

    prod = Settings(
        _env_file=None,
        app_env="prod",
        database_url="postgresql+asyncpg://x/y",
        secret_key="k",
    )
    assert prod.allow_loopback is False

    forced = Settings(
        _env_file=None,
        app_env="prod",
        ssrf_allow_loopback=True,
        database_url="postgresql+asyncpg://x/y",
        secret_key="k",
    )
    assert forced.allow_loopback is True
