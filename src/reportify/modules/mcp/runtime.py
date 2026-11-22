"""MCP agent plane: per-run toolsets (03 §8.2).

One ``MCPToolset`` per server per run, lazily connected, filtered down to the
tools this run is authorized to see. A server that fails a short reachability
probe is dropped from the run (and reported) instead of failing the whole run.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import UUID

from pydantic_ai.mcp import MCPToolset
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.db.models import MCPServer, Secret
from reportify.db.repositories import mcp as mcp_repo
from reportify.modules.mcp.client import MCPServerSpec
from reportify.modules.security.secrets import SecretService
from reportify.modules.tools.naming import mcp_prefix, sanitize_segment
from reportify.modules.tools.schemas import ToolSpec

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 5.0


@dataclass
class MCPToolsetBundle:
    toolsets: list[MCPToolset] = field(default_factory=list)
    attached: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


class MCPRuntime:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_service: SecretService,
        *,
        allow_loopback: bool = False,
        connect_timeout: float = 30.0,
        read_timeout: float = 60.0,
        probe_timeout: float = PROBE_TIMEOUT_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._secret_service = secret_service
        self._allow_loopback = allow_loopback
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._probe_timeout = probe_timeout

    async def toolsets(self, specs: list[ToolSpec]) -> MCPToolsetBundle:
        """Build toolsets for every server that has authorized tools in ``specs``."""
        allowed_by_slug: dict[str, set[str]] = {}
        raw_by_slug: dict[str, set[str]] = {}
        for spec in specs:
            if spec.kind != "mcp" or not spec.source_slug:
                continue
            allowed_by_slug.setdefault(spec.source_slug, set()).add(spec.model_name)
            raw_name = spec.model_name_raw or spec.model_name
            raw_by_slug.setdefault(spec.source_slug, set()).add(raw_name)

        bundle = MCPToolsetBundle()
        if not allowed_by_slug:
            return bundle

        async with self._session_factory() as session:
            servers = {server.slug: server for server in await mcp_repo.list_servers(session)}
            for slug, allowed in allowed_by_slug.items():
                server = servers.get(slug)
                if server is None or not server.enabled or server.status == "error":
                    bundle.skipped.append(slug)
                    continue
                spec = await self._spec(session, server)
                toolset = self._build(server.slug, spec, allowed, raw_by_slug[slug])
                if await self._reachable(spec):
                    bundle.toolsets.append(toolset)
                    bundle.attached.append(slug)
                else:
                    bundle.unavailable.append(slug)
                    logger.warning("mcp server unreachable for run", extra={"mcp_slug": slug})
        return bundle

    def _build(
        self,
        slug: str,
        spec: MCPServerSpec,
        allowed_model_names: set[str],
        allowed_raw_names: set[str],
    ) -> MCPToolset:
        prefix = mcp_prefix(slug)
        separator = f"{prefix}_"

        def _allowed(ctx, tool_definition) -> bool:  # noqa: ANN001 - SDK signature
            name = getattr(tool_definition, "name", "") or ""
            if name in allowed_model_names or name in allowed_raw_names:
                return True
            return name.startswith(separator) and name[len(separator) :] in allowed_raw_names

        return (
            MCPToolset(
                spec.url,
                id=f"mcp_{sanitize_segment(slug)}",
                headers=spec.request_headers(),
                init_timeout=self._connect_timeout,
                read_timeout=spec.read_timeout,
                tool_error_behavior="retry",
                include_instructions=False,
            )
            .prefixed(prefix)
            .filtered(_allowed)
        )

    async def _reachable(self, spec: MCPServerSpec) -> bool:
        """Probe with a plain toolset: filtered toolsets need a run context."""
        probe = MCPToolset(
            spec.url,
            headers=spec.request_headers(),
            init_timeout=self._connect_timeout,
            read_timeout=spec.read_timeout,
            include_instructions=False,
        )
        try:
            async with asyncio.timeout(self._probe_timeout):
                async with probe:
                    await probe.list_tools()
            return True
        except Exception as exc:  # noqa: BLE001 - any failure means "skip this server"
            logger.debug(
                "mcp probe failed: %s: %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            return False

    async def _spec(self, session: AsyncSession, server: MCPServer) -> MCPServerSpec:
        token: str | None = None
        if server.auth_type == "bearer" and server.secret_id is not None:
            secret = await session.get(Secret, server.secret_id)
            if secret is not None:
                token = self._secret_service.decrypt(
                    secret.ciphertext,
                    secret.nonce,
                    secret.key_version,
                )
        options = server.options or {}
        return MCPServerSpec(
            url=server.url or "",
            headers=dict(server.headers or {}),
            bearer_token=token,
            connect_timeout=self._connect_timeout,
            read_timeout=float(options.get("read_timeout_seconds", self._read_timeout)),
        )

    @staticmethod
    def server_id_for(specs: list[ToolSpec], slug: str) -> UUID | None:
        for spec in specs:
            if spec.source_slug == slug:
                return spec.source_id
        return None
