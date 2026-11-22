"""Shared helpers for MCP integration tests."""

from __future__ import annotations

from uuid import uuid4


def unique_slug(prefix: str = "probe") -> str:
    """Slugs must be unique because the test database is shared across tests."""
    return f"{prefix}-{uuid4().hex[:8]}"


def expected_model_name(slug: str, tool: str) -> str:
    from reportify.modules.tools.naming import mcp_model_name

    return mcp_model_name(slug, tool)
