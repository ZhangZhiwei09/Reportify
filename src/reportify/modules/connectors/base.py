"""Connector protocol and per-data-source registry."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.db.models import DataSource
from reportify.modules.connectors.errors import (
    ConnectionFailed,
    DataSourceDisabled,
    DataSourceNotFound,
)
from reportify.modules.connectors.postgres import PostgresConnector
from reportify.modules.connectors.schemas import Health, Page, QuerySpec, ResultSet, TableSchema
from reportify.modules.security.secrets import SecretService


class DataConnector(Protocol):
    async def test_connection(self) -> Health: ...

    async def inspect_schema(self) -> list[TableSchema]: ...

    async def execute(
        self,
        spec: QuerySpec,
        *,
        purpose: str = "analysis",
        max_limit: int | None = None,
    ) -> ResultSet: ...

    async def fetch_page(self, snapshot_id: UUID, offset: int, limit: int) -> Page: ...

    async def close(self) -> None: ...


class ConnectorRegistry:
    """Create and cache one connector/engine per data source."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_service: SecretService,
    ) -> None:
        self._session_factory = session_factory
        self._secret_service = secret_service
        self._connectors: dict[UUID, PostgresConnector] = {}

    async def get(self, data_source_id: UUID) -> PostgresConnector:
        cached = self._connectors.get(data_source_id)
        if cached is not None:
            return cached

        async with self._session_factory() as session:
            data_source = await session.get(DataSource, data_source_id)
            if data_source is None:
                raise DataSourceNotFound(f"data source not found: {data_source_id}")
            if data_source.status == "disabled":
                raise DataSourceDisabled(f"data source is disabled: {data_source.name}")
            if data_source.secret_id is None:
                raise ConnectionFailed("data source has no stored credential")

            # The import is local to avoid a model import cycle in type checkers.
            from reportify.db.models import Secret

            secret = await session.get(Secret, data_source.secret_id)
            if secret is None:
                raise ConnectionFailed("credential record is missing")

            password = self._secret_service.decrypt(
                secret.ciphertext,
                secret.nonce,
                secret.key_version,
            )
            connector = PostgresConnector(
                data_source=data_source,
                password=password,
                session_factory=self._session_factory,
            )

        self._connectors[data_source_id] = connector
        return connector

    async def invalidate(self, data_source_id: UUID) -> None:
        connector = self._connectors.pop(data_source_id, None)
        if connector is not None:
            await connector.close()

    async def close_all(self) -> None:
        for connector in list(self._connectors.values()):
            await connector.close()
        self._connectors.clear()
