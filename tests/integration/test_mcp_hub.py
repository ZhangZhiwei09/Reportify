from __future__ import annotations

import pytest

from reportify.core.errors import Conflict, NotFound, ValidationFailed
from reportify.modules.mcp.schemas import (
    GrantRequest,
    MCPServerCreate,
    MCPServerUpdate,
)
from tests.integration.fake_mcp import closed_port_url
from tests.integration.mcp_helpers import unique_slug


def _create(slug: str, url: str, **overrides) -> MCPServerCreate:
    payload = {
        "name": f"MCP {slug}",
        "slug": slug,
        "url": url,
    }
    payload.update(overrides)
    return MCPServerCreate(**payload)


async def test_create_test_and_discover(mcp_hub, fake_mcp) -> None:
    slug = unique_slug()
    created = await mcp_hub.create(_create(slug, fake_mcp.url))
    assert created.status == "unknown"
    assert created.has_secret is False

    tested = await mcp_hub.test(created.id)
    assert tested.ok is True
    assert tested.tool_count == 3
    assert tested.status == "connected"

    discovered = await mcp_hub.discover(created.id)
    assert discovered.tools_discovered == 3
    assert discovered.tools_added == 3
    assert discovered.schema_changed == []

    tools = await mcp_hub.list_tools(created.id)
    names = {tool.model_name for tool in tools}
    assert names == {
        f"mcp_{slug.replace('-', '_')}_echo",
        f"mcp_{slug.replace('-', '_')}_slow",
        f"mcp_{slug.replace('-', '_')}_boom",
    }
    # Conservative default: every discovered tool is a write tool with no grant.
    assert all(tool.risk_level == "write" for tool in tools)
    assert all(tool.granted is False for tool in tools)


async def test_discovery_is_idempotent(mcp_hub, fake_mcp) -> None:
    slug = unique_slug()
    created = await mcp_hub.create(_create(slug, fake_mcp.url))
    await mcp_hub.discover(created.id)
    second = await mcp_hub.discover(created.id)

    assert second.tools_added == 0
    assert second.tools_updated == 3
    assert second.tools_removed == 0


async def test_discovery_detects_new_and_removed_tools(mcp_hub, fake_mcp) -> None:
    slug = unique_slug()
    created = await mcp_hub.create(_create(slug, fake_mcp.url))
    await mcp_hub.discover(created.id)

    def extra(value: str) -> str:
        """A tool added later."""
        return value

    fake_mcp.add_tool("extra", extra)
    added = await mcp_hub.discover(created.id)
    assert added.tools_added == 1

    fake_mcp.remove_tool("extra")
    removed = await mcp_hub.discover(created.id)
    assert removed.tools_removed == 1
    remaining = {tool.model_name: tool for tool in await mcp_hub.list_tools(created.id)}
    extra = next(item for name, item in remaining.items() if name.endswith("_extra"))
    assert extra.enabled is False


async def test_schema_drift_resets_risk_acknowledgement(mcp_hub, fake_mcp) -> None:
    slug = unique_slug()
    created = await mcp_hub.create(_create(slug, fake_mcp.url))
    await mcp_hub.discover(created.id)

    tools = await mcp_hub.list_tools(created.id)
    echo = next(tool for tool in tools if tool.model_name.endswith("_echo"))
    granted = await mcp_hub.set_grant(
        echo.id,
        GrantRequest(allowed=True, risk_level="read", risk_acknowledged=True),
    )
    assert granted.granted is True

    fake_mcp.mutate_echo_description()
    drifted = await mcp_hub.discover(created.id)
    assert "echo" in drifted.schema_changed

    after = await mcp_hub.list_tools(created.id)
    echo_after = next(tool for tool in after if tool.model_name.endswith("_echo"))
    assert echo_after.granted is True
    assert echo_after.risk_acknowledged is False


async def test_grant_requires_risk_acknowledgement(mcp_hub, fake_mcp) -> None:
    slug = unique_slug()
    created = await mcp_hub.create(_create(slug, fake_mcp.url))
    await mcp_hub.discover(created.id)
    tool = (await mcp_hub.list_tools(created.id))[0]

    with pytest.raises(ValidationFailed):
        await mcp_hub.set_grant(tool.id, GrantRequest(allowed=True))

    granted = await mcp_hub.set_grant(
        tool.id,
        GrantRequest(allowed=True, risk_level="read", risk_acknowledged=True),
    )
    assert granted.granted is True
    assert granted.risk_level == "read"

    revoked = await mcp_hub.revoke_grant(tool.id)
    assert revoked.granted is False


async def test_ssrf_rejects_metadata_endpoint(mcp_hub) -> None:
    with pytest.raises(ValidationFailed):
        await mcp_hub.create(_create(unique_slug(), "http://169.254.169.254/mcp"))


async def test_ssrf_rejects_public_http(mcp_hub) -> None:
    with pytest.raises(ValidationFailed):
        await mcp_hub.create(_create(unique_slug(), "http://example.com/mcp"))


async def test_duplicate_slug_conflicts(mcp_hub, fake_mcp) -> None:
    slug = unique_slug()
    await mcp_hub.create(_create(slug, fake_mcp.url))
    with pytest.raises(Conflict):
        await mcp_hub.create(_create(slug, fake_mcp.url, name=f"other {slug}"))


async def test_bearer_token_is_stored_encrypted(mcp_hub, fake_mcp, session_factory) -> None:
    from sqlalchemy import text

    slug = unique_slug()
    created = await mcp_hub.create(
        _create(slug, fake_mcp.url, auth_type="bearer", token="s3cr3t-token")
    )
    assert created.has_secret is True

    async with session_factory() as session:
        row = (
            await session.execute(
                text("select ciphertext, nonce from secret where name = :name"),
                {"name": f"mcp-server:{slug}"},
            )
        ).first()
    assert row is not None
    assert b"s3cr3t-token" not in bytes(row[0])


async def test_unreachable_server_marks_error(mcp_hub) -> None:
    slug = unique_slug()
    created = await mcp_hub.create(_create(slug, closed_port_url()))
    tested = await mcp_hub.test(created.id)
    assert tested.ok is False
    assert tested.status == "error"

    fetched = await mcp_hub.get(created.id)
    assert fetched.status == "error"
    assert fetched.last_error


async def test_disable_hides_tools(mcp_hub, fake_mcp) -> None:
    slug = unique_slug()
    created = await mcp_hub.create(_create(slug, fake_mcp.url))
    await mcp_hub.discover(created.id)
    await mcp_hub.disable(created.id)

    fetched = await mcp_hub.get(created.id)
    assert fetched.enabled is False
    assert fetched.status == "disabled"
    tools = await mcp_hub.list_tools(created.id)
    assert tools and all(tool.enabled is False for tool in tools)


async def test_unknown_server_is_404(mcp_hub) -> None:
    import uuid

    with pytest.raises(NotFound):
        await mcp_hub.get(uuid.uuid4())


async def test_update_url_and_options(mcp_hub, fake_mcp) -> None:
    slug = unique_slug()
    created = await mcp_hub.create(_create(slug, fake_mcp.url))
    updated = await mcp_hub.update(
        created.id,
        MCPServerUpdate(url=fake_mcp.url, enabled=True),
    )
    assert updated.url == fake_mcp.url
