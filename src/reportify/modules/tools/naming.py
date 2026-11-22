"""Tool naming rules (03 §3).

Database names are namespaced (``mcp.github.search_issues``); model-visible names
must satisfy function-name constraints (``mcp_github_search_issues``). Both
directions live here so the registry and the MCP hub cannot drift.
"""

from __future__ import annotations

import re

_SEGMENT_CLEANUP = re.compile(r"[^A-Za-z0-9_]+")
MCP_PREFIX = "mcp_"


def sanitize_segment(value: str) -> str:
    cleaned = _SEGMENT_CLEANUP.sub("_", value).strip("_").lower()
    if not cleaned:
        return "tool"
    if cleaned[0].isdigit():
        return f"t_{cleaned}"
    return cleaned


def mcp_database_name(slug: str, tool_name: str) -> str:
    return f"mcp.{slug}.{tool_name}"


def mcp_model_name(slug: str, tool_name: str) -> str:
    return f"{mcp_prefix(slug)}_{sanitize_segment(tool_name)}"


def mcp_prefix(slug: str) -> str:
    """Prefix without a trailing separator: ``prefixed()`` adds ``_`` itself."""
    return f"{MCP_PREFIX}{sanitize_segment(slug)}"


def parse_database_name(name: str) -> tuple[str, str] | None:
    """Split ``mcp.<slug>.<tool>`` into its parts, or return None."""
    if not name.startswith("mcp."):
        return None
    parts = name.split(".", 2)
    if len(parts) != 3 or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def is_mcp_model_name(name: str) -> bool:
    return name.startswith(MCP_PREFIX)
