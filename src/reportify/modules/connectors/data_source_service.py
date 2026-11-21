"""Data source lifecycle and credential handling."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.db.models import DataSource, Secret
from reportify.modules.connectors.base import ConnectorRegistry
from reportify.modules.connectors.errors import (
    DataLayerError,
    DataSourceNameConflict,
    DataSourceNotFound,
)
from reportify.modules.connectors.schemas import Health
from reportify.modules.security.secrets import SecretService

_DEFAULT_OPTIONS: dict[str, Any] = {
    "schema_allowlist": ["public"],
    "read_only": True,
    "statement_timeout_ms": 30_000,
    "max_rows": 10_000,
}


class DataSourceService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        secret_service: SecretService,
        registry: ConnectorRegistry,
    ) -> None:
        self._session_factory = session_factory
        self._secret_service = secret_service
        self._registry = registry

    async def create(
        self,
        *,
        name: str,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        ssl_mode: str = "prefer",
        options: dict[str, Any] | None = None,
    ) -> DataSource:
        encrypted = self._secret_service.encrypt(password)
        merged_options = {**_DEFAULT_OPTIONS, **(options or {})}

        async with self._session_factory() as session:
            existing = await session.execute(
                select(DataSource).where(DataSource.name == name)
            )
            if existing.scalar_one_or_none() is not None:
                raise DataSourceNameConflict(f"data source name already exists: {name}")

            secret = Secret(
                name=f"data-source:{name}",
                ciphertext=encrypted.ciphertext,
                nonce=encrypted.nonce,
                key_version=encrypted.key_version,
            )
            session.add(secret)
            await session.flush()

            data_source = DataSource(
                name=name,
                type="postgresql",
                host=host,
                port=port,
                database=database,
                username=username,
                ssl_mode=ssl_mode,
                secret_id=secret.id,
                options=merged_options,
                status="active",
            )
            session.add(data_source)
            await session.commit()
            return data_source

    async def list(self) -> list[DataSource]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(DataSource).order_by(DataSource.name)
            )
            return list(result.scalars())

    async def get(self, data_source_id: UUID) -> DataSource:
        async with self._session_factory() as session:
            data_source = await session.get(DataSource, data_source_id)
            if data_source is None:
                raise DataSourceNotFound(f"data source not found: {data_source_id}")
            return data_source

    async def update(
        self,
        data_source_id: UUID,
        *,
        fields: dict[str, Any],
        password: str | None = None,
    ) -> DataSource:
        async with self._session_factory() as session:
            async with session.begin():
                data_source = await session.get(DataSource, data_source_id)
                if data_source is None:
                    raise DataSourceNotFound(f"data source not found: {data_source_id}")

                new_name = fields.get("name")
                if new_name and new_name != data_source.name:
                    existing = await session.execute(
                        select(DataSource).where(
                            DataSource.name == new_name,
                            DataSource.id != data_source_id,
                        )
                    )
                    if existing.scalar_one_or_none() is not None:
                        raise DataSourceNameConflict(
                            f"data source name already exists: {new_name}"
                        )
                    data_source.name = new_name

                for field in (
                    "host",
                    "port",
                    "database",
                    "username",
                    "ssl_mode",
                    "options",
                ):
                    if field in fields and fields[field] is not None:
                        setattr(data_source, field, fields[field])

                if password:
                    encrypted = self._secret_service.encrypt(password)
                    secret = (
                        await session.get(Secret, data_source.secret_id)
                        if data_source.secret_id
                        else None
                    )
                    if secret is None:
                        secret = Secret(
                            name=f"data-source:{data_source.name}",
                            ciphertext=encrypted.ciphertext,
                            nonce=encrypted.nonce,
                            key_version=encrypted.key_version,
                        )
                        session.add(secret)
                        await session.flush()
                        data_source.secret_id = secret.id
                    else:
                        secret.ciphertext = encrypted.ciphertext
                        secret.nonce = encrypted.nonce
                        secret.key_version = encrypted.key_version

                data_source.status = "active"
                data_source.last_error = None

        await self._registry.invalidate(data_source_id)
        return data_source

    async def disable(self, data_source_id: UUID) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                data_source = await session.get(DataSource, data_source_id)
                if data_source is None:
                    raise DataSourceNotFound(f"data source not found: {data_source_id}")
                data_source.status = "disabled"
        await self._registry.invalidate(data_source_id)

    async def test(self, data_source_id: UUID) -> Health:
        try:
            connector = await self._registry.get(data_source_id)
            health = await connector.test_connection()
        except DataLayerError as exc:
            await self._mark_error(data_source_id, exc.detail)
            raise

        async with self._session_factory() as session:
            async with session.begin():
                data_source = await session.get(DataSource, data_source_id)
                if data_source is not None:
                    data_source.status = "active"
                    data_source.last_tested_at = datetime.now(UTC)
                    data_source.last_error = None
        return health

    async def _mark_error(self, data_source_id: UUID, detail: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                data_source = await session.get(DataSource, data_source_id)
                if data_source is not None:
                    data_source.status = "error"
                    data_source.last_tested_at = datetime.now(UTC)
                    data_source.last_error = detail[:500]
