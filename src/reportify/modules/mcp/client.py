"""MCP client boundary (03 §8.1).

The MVP uses one stack only: PydanticAI's ``MCPToolset`` (which wraps the FastMCP
client) for both the management plane (short-lived context) and the agent plane
(per-run toolset). ``MCPClientFactory`` keeps the official SDK replaceable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from reportify.core.ssrf import SSRFError, validate_url

DEFAULT_CONNECT_TIMEOUT = 30.0
DEFAULT_READ_TIMEOUT = 60.0


class MCPConnectionError(RuntimeError):
    """A connection or protocol failure, already safe to show to a user."""

    code = "dependency_unavailable"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class MCPServerSpec:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    bearer_token: str | None = None
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT
    read_timeout: float = DEFAULT_READ_TIMEOUT

    def request_headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers


@dataclass(frozen=True)
class MCPToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any] = field(default_factory=dict)

    @property
    def schema_hash(self) -> str:
        canonical = json.dumps(
            {"input": self.input_schema, "description": self.description},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class MCPDiscovery:
    tools: list[MCPToolInfo]
    server_info: dict[str, Any] = field(default_factory=dict)
    protocol_version: str | None = None


class MCPClientFactory(Protocol):
    async def discover(self, spec: MCPServerSpec, *, allow_loopback: bool) -> MCPDiscovery: ...


class PydanticAIMCPClient:
    """Discovery over a short-lived ``MCPToolset`` context."""

    async def discover(self, spec: MCPServerSpec, *, allow_loopback: bool) -> MCPDiscovery:
        try:
            validate_url(spec.url, allow_loopback=allow_loopback)
        except SSRFError as exc:
            raise MCPConnectionError(f"URL rejected by SSRF policy: {exc.reason}") from exc

        from pydantic_ai.mcp import MCPToolset

        toolset = MCPToolset(
            spec.url,
            headers=spec.request_headers(),
            init_timeout=spec.connect_timeout,
            read_timeout=spec.read_timeout,
            include_instructions=False,
        )
        try:
            async with toolset:
                tools = await toolset.list_tools()
                info = getattr(toolset, "server_info", None)
        except SSRFError as exc:
            raise MCPConnectionError(f"URL rejected by SSRF policy: {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001 - normalised for the API layer
            raise MCPConnectionError(_safe_reason(exc)) from exc

        described = [
            MCPToolInfo(
                name=tool.name,
                description=tool.description or "",
                input_schema=dict(tool.input_schema or {}),
                annotations=dict(getattr(tool, "annotations", {}) or {}),
            )
            for tool in tools
        ]
        return MCPDiscovery(
            tools=described,
            server_info=_as_dict(info),
            protocol_version=getattr(info, "protocol_version", None),
        )


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        data = value.model_dump()
        return {key: item for key, item in data.items() if item is not None}
    return {
        key: item
        for key, item in vars(value).items()
        if not key.startswith("_") and item is not None
    }


def _safe_reason(exc: Exception) -> str:
    """Never leak headers, tokens or full URLs into stored errors."""
    message = str(exc).strip() or type(exc).__name__
    if "timed out" in message.lower():
        return "connection timed out"
    if "401" in message or "unauthorized" in message.lower():
        return "authentication failed"
    if "403" in message or "forbidden" in message.lower():
        return "access forbidden"
    if "connect" in message.lower() and "error" in message.lower():
        return "connection failed"
    return f"{type(exc).__name__}: {message[:200]}"
