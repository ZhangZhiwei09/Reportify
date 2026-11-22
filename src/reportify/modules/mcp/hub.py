"""MCP Hub: the management plane (03 §7).

Owns server configuration, connection testing, tool discovery, and per-tool
grants. The agent plane (``MCPRuntime``) only consumes what this module persists.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.core.errors import Conflict, InvalidArgument, NotFound, ValidationFailed
from reportify.core.ssrf import SSRFError, validate_url
from reportify.db.models import MCPServer, Secret, ToolDefinition, ToolGrant
from reportify.db.repositories import mcp as mcp_repo
from reportify.db.repositories import tools as tools_repo
from reportify.modules.mcp.client import (
    MCPClientFactory,
    MCPConnectionError,
    MCPDiscovery,
    MCPServerSpec,
    PydanticAIMCPClient,
)
from reportify.modules.mcp.schemas import (
    DiscoveryResult,
    GrantRequest,
    MCPServerCreate,
    MCPServerRead,
    MCPServerUpdate,
    MCPTestResult,
    MCPToolView,
)
from reportify.modules.security.secrets import SecretService
from reportify.modules.tools.naming import mcp_database_name, mcp_model_name


class MCPHub:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_service: SecretService,
        *,
        allow_loopback: bool = False,
        connect_timeout: float = 30.0,
        read_timeout: float = 60.0,
        client: MCPClientFactory | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._secret_service = secret_service
        self._allow_loopback = allow_loopback
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._client: MCPClientFactory = client or PydanticAIMCPClient()

    # ------------------------------------------------------------------ CRUD

    async def create(self, payload: MCPServerCreate) -> MCPServerRead:
        self._validate_url(payload.url)
        if payload.auth_type == "bearer" and payload.token is None:
            raise InvalidArgument("bearer auth requires a token")

        async with self._session_factory() as session:
            if await mcp_repo.get_by_slug(session, payload.slug) is not None:
                raise Conflict(f"mcp server slug already exists: {payload.slug}")
            if await mcp_repo.get_by_name(session, payload.name) is not None:
                raise Conflict(f"mcp server name already exists: {payload.name}")

            secret_id = None
            if payload.token is not None:
                encrypted = self._secret_service.encrypt(payload.token.get_secret_value())
                secret = Secret(
                    name=f"mcp-server:{payload.slug}",
                    ciphertext=encrypted.ciphertext,
                    nonce=encrypted.nonce,
                    key_version=encrypted.key_version,
                )
                session.add(secret)
                await session.flush()
                secret_id = secret.id

            server = await mcp_repo.create_server(
                session,
                name=payload.name,
                slug=payload.slug,
                transport="streamable_http",
                url=payload.url,
                auth_type=payload.auth_type,
                secret_id=secret_id,
                headers=payload.headers,
                options=payload.options.model_dump(),
                enabled=payload.enabled,
                status="unknown",
            )
            return self._read(server, has_secret=secret_id is not None)

    async def list(self) -> list[MCPServerRead]:
        async with self._session_factory() as session:
            servers = await mcp_repo.list_servers(session)
            return [self._read(server) for server in servers]

    async def get(self, server_id: UUID) -> MCPServerRead:
        async with self._session_factory() as session:
            server = await mcp_repo.get_server(session, server_id)
            if server is None:
                raise NotFound(f"mcp server not found: {server_id}")
            return self._read(server)

    async def update(self, server_id: UUID, payload: MCPServerUpdate) -> MCPServerRead:
        if payload.url is not None:
            self._validate_url(payload.url)

        async with self._session_factory() as session:
            server = await mcp_repo.get_server(session, server_id)
            if server is None:
                raise NotFound(f"mcp server not found: {server_id}")

            fields: dict[str, object] = {}
            if payload.name is not None:
                fields["name"] = payload.name
            if payload.url is not None:
                fields["url"] = payload.url
            if payload.auth_type is not None:
                fields["auth_type"] = payload.auth_type
            if payload.headers is not None:
                fields["headers"] = payload.headers
            if payload.options is not None:
                fields["options"] = payload.options.model_dump()
            if payload.enabled is not None:
                fields["enabled"] = payload.enabled
                if payload.enabled is False:
                    fields["status"] = "disabled"

            if payload.token is not None:
                encrypted = self._secret_service.encrypt(payload.token.get_secret_value())
                secret = (
                    await session.get(Secret, server.secret_id) if server.secret_id else None
                )
                if secret is None:
                    secret = Secret(
                        name=f"mcp-server:{server.slug}",
                        ciphertext=encrypted.ciphertext,
                        nonce=encrypted.nonce,
                        key_version=encrypted.key_version,
                    )
                    session.add(secret)
                    await session.flush()
                    fields["secret_id"] = secret.id
                else:
                    secret.ciphertext = encrypted.ciphertext
                    secret.nonce = encrypted.nonce
                    secret.key_version = encrypted.key_version

            server = await mcp_repo.update_server(session, server, **fields)
            return self._read(server)

    async def disable(self, server_id: UUID) -> MCPServerRead:
        """Soft delete: keep the row and audit trail, hide every tool."""
        async with self._session_factory() as session:
            server = await mcp_repo.get_server(session, server_id)
            if server is None:
                raise NotFound(f"mcp server not found: {server_id}")
            server.enabled = False
            server.status = "disabled"
            await session.commit()
            rows = await tools_repo.list_mcp_definitions(session, source_id=server_id)
            for definition, _server in rows:
                definition.enabled = False
            await session.commit()
            await session.refresh(server)
            return self._read(server)

    # --------------------------------------------------------- test/discover

    async def test(self, server_id: UUID) -> MCPTestResult:
        async with self._session_factory() as session:
            server = await mcp_repo.get_server(session, server_id)
            if server is None:
                raise NotFound(f"mcp server not found: {server_id}")
            spec = await self._spec(session, server)
            session_factory = self._session_factory

        try:
            discovery = await self._client.discover(
                spec,
                allow_loopback=self._allow_loopback,
            )
        except MCPConnectionError as exc:
            async with session_factory() as session:
                await mcp_repo.set_status(
                    session,
                    server_id,
                    status="error",
                    last_error=str(exc),
                )
            return MCPTestResult(ok=False, status="error", error=str(exc))

        async with session_factory() as session:
            await mcp_repo.set_status(
                session,
                server_id,
                status="connected",
                last_error=None,
                server_info=discovery.server_info,
                protocol_version=discovery.protocol_version,
            )
        return MCPTestResult(
            ok=True,
            status="connected",
            tool_count=len(discovery.tools),
            server_info=discovery.server_info,
            protocol_version=discovery.protocol_version,
        )

    async def discover(self, server_id: UUID) -> DiscoveryResult:
        async with self._session_factory() as session:
            server = await mcp_repo.get_server(session, server_id)
            if server is None:
                raise NotFound(f"mcp server not found: {server_id}")
            spec = await self._spec(session, server)
            slug = server.slug
            session_factory = self._session_factory

        try:
            discovery = await self._client.discover(
                spec,
                allow_loopback=self._allow_loopback,
            )
        except MCPConnectionError as exc:
            async with session_factory() as session:
                await mcp_repo.set_status(
                    session,
                    server_id,
                    status="error",
                    last_error=str(exc),
                )
            raise Conflict(f"mcp discovery failed: {exc}") from exc

        result = await self._persist_discovery(server_id, slug, discovery)
        async with session_factory() as session:
            await mcp_repo.set_status(
                session,
                server_id,
                status="connected",
                last_error=None,
                server_info=discovery.server_info,
                protocol_version=discovery.protocol_version,
            )
        return result

    async def _persist_discovery(
        self,
        server_id: UUID,
        slug: str,
        discovery: MCPDiscovery,
    ) -> DiscoveryResult:
        added = updated = 0
        changed: list[str] = []
        names = [tool.name for tool in discovery.tools]

        async with self._session_factory() as session:
            for tool in discovery.tools:
                _, schema_changed = await mcp_repo.upsert_cache(
                    session,
                    server_id=server_id,
                    tool_name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    annotations=tool.annotations,
                    schema_hash=tool.schema_hash,
                )
                definition, created = await tools_repo.upsert_mcp_definition(
                    session,
                    name=mcp_database_name(slug, tool.name),
                    source_id=server_id,
                    display_name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                )
                definition.enabled = True
                await session.commit()
                if created:
                    added += 1
                else:
                    updated += 1
                if schema_changed and not created:
                    changed.append(tool.name)
                    # Write tools must be re-confirmed after a schema change.
                    await tools_repo.reset_grant_acknowledgement(
                        session,
                        tool_definition_id=definition.id,
                    )

            removed = await mcp_repo.delete_cache_not_in(session, server_id, names)

        for tool_name in removed:
            async with self._session_factory() as session:
                await tools_repo.set_definition_enabled(
                    session,
                    source_id=server_id,
                    name=mcp_database_name(slug, tool_name),
                    enabled=False,
                )

        return DiscoveryResult(
            server_id=server_id,
            tools_discovered=len(discovery.tools),
            tools_added=added,
            tools_updated=updated,
            tools_removed=len(removed),
            schema_changed=changed,
            status="connected",
            server_info=discovery.server_info,
        )

    # ----------------------------------------------------------- tool grants

    async def list_tools(self, server_id: UUID) -> list[MCPToolView]:
        async with self._session_factory() as session:
            server = await mcp_repo.get_server(session, server_id)
            if server is None:
                raise NotFound(f"mcp server not found: {server_id}")
            rows = await tools_repo.list_mcp_definitions(session, source_id=server_id)
            views: list[MCPToolView] = []
            for definition, _server in rows:
                grants = await tools_repo.grants_for(session, definition.id)
                grant = next(
                    (item for item in grants if item.scope == "global"),
                    None,
                )
                views.append(self._view(definition, server.slug, grant))
            return views

    async def set_grant(self, tool_id: UUID, payload: GrantRequest) -> MCPToolView:
        async with self._session_factory() as session:
            definition = await session.get(ToolDefinition, tool_id)
            if definition is None or definition.kind != "mcp":
                raise NotFound(f"mcp tool not found: {tool_id}")
            server = await mcp_repo.get_server(session, definition.source_id or UUID(int=0))
            if server is None:
                raise NotFound(f"mcp server not found for tool: {tool_id}")

            risk_level = payload.risk_level or definition.risk_level
            if payload.allowed and risk_level in {"write", "destructive"}:
                if not payload.risk_acknowledged:
                    raise ValidationFailed(
                        "risk_acknowledged must be true to grant a write tool"
                    )
            definition.risk_level = risk_level
            await session.commit()

            grant = await tools_repo.upsert_grant(
                session,
                tool_definition_id=definition.id,
                scope="global",
                scope_id=None,
                allowed=payload.allowed,
                risk_acknowledged=payload.risk_acknowledged,
                granted_by="local",
            )
            return self._view(definition, server.slug, grant)

    async def revoke_grant(self, tool_id: UUID) -> MCPToolView:
        async with self._session_factory() as session:
            definition = await session.get(ToolDefinition, tool_id)
            if definition is None or definition.kind != "mcp":
                raise NotFound(f"mcp tool not found: {tool_id}")
            server = await mcp_repo.get_server(session, definition.source_id or UUID(int=0))
            if server is None:
                raise NotFound(f"mcp server not found for tool: {tool_id}")
            grant = await tools_repo.upsert_grant(
                session,
                tool_definition_id=definition.id,
                scope="global",
                scope_id=None,
                allowed=False,
                risk_acknowledged=False,
                granted_by="local",
            )
            return self._view(definition, server.slug, grant)

    # --------------------------------------------------------------- helpers

    def _validate_url(self, url: str) -> None:
        try:
            validate_url(url, allow_loopback=self._allow_loopback)
        except SSRFError as exc:
            raise ValidationFailed(f"url rejected by SSRF policy: {exc.reason}") from exc

    async def _spec(self, session: AsyncSession, server: MCPServer) -> MCPServerSpec:
        token: str | None = None
        if server.auth_type == "bearer" and server.secret_id is not None:
            secret = await session.get(Secret, server.secret_id)
            if secret is None:
                raise NotFound("mcp server credential is missing")
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

    def _read(self, server: MCPServer, *, has_secret: bool | None = None) -> MCPServerRead:
        return MCPServerRead(
            id=server.id,
            name=server.name,
            slug=server.slug,
            transport=server.transport,
            url=server.url,
            auth_type=server.auth_type,
            has_secret=server.secret_id is not None if has_secret is None else has_secret,
            headers=_public_headers(server.headers),
            options=server.options or {},
            enabled=server.enabled,
            status=server.status,
            last_tested_at=server.last_tested_at,
            last_error=server.last_error,
            protocol_version=server.protocol_version,
            server_info=server.server_info or {},
            created_at=server.created_at,
        )

    def _view(
        self,
        definition: ToolDefinition,
        slug: str,
        grant: ToolGrant | None,
    ) -> MCPToolView:
        return MCPToolView(
            id=definition.id,
            name=definition.name,
            model_name=mcp_model_name(slug, definition.name.split(".", 2)[-1]),
            server_id=definition.source_id or UUID(int=0),
            server_slug=slug,
            display_name=definition.display_name,
            description=definition.description,
            risk_level=definition.risk_level,
            enabled=definition.enabled,
            requires_approval=definition.requires_approval,
            granted=bool(grant and grant.allowed),
            risk_acknowledged=bool(grant and grant.risk_acknowledged),
        )


def _public_headers(headers: dict[str, object] | None) -> dict[str, object]:
    """Never echo credentials; they live in ``secret`` and are set at call time."""
    if not headers:
        return {}
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in {"authorization", "cookie", "proxy-authorization"}
    }
