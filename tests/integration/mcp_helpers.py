"""Shared helpers for MCP integration tests."""

from __future__ import annotations

from uuid import uuid4


def unique_slug(prefix: str = "probe") -> str:
    """Slugs must be unique because the test database is shared across tests."""
    return f"{prefix}-{uuid4().hex[:8]}"


def expected_model_name(slug: str, tool: str) -> str:
    from reportify.modules.tools.naming import mcp_model_name

    return mcp_model_name(slug, tool)


def create_server(client, url: str, slug: str, **extra) -> dict:
    response = client.post(
        "/api/v1/mcp/servers",
        json={"name": f"MCP {slug}", "slug": slug, "url": url, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def discover(client, server_id: str) -> dict:
    response = client.post(f"/api/v1/mcp/servers/{server_id}/discover")
    assert response.status_code == 200, response.text
    return response.json()


def find_tool(client, server_id: str, tool_name: str) -> dict:
    tools = client.get(f"/api/v1/mcp/servers/{server_id}/tools").json()
    return next(item for item in tools if item["name"].endswith(f".{tool_name}"))


def grant(client, server_id: str, tool_name: str, *, risk: str = "read", ack: bool = True) -> dict:
    tool = find_tool(client, server_id, tool_name)
    response = client.put(
        f"/api/v1/mcp/tools/{tool['id']}/grant",
        json={"allowed": True, "risk_level": risk, "risk_acknowledged": ack},
    )
    assert response.status_code == 200, response.text
    return response.json()
