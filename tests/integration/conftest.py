from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from reportify.api.app import create_app
from reportify.core.config import Settings, get_settings
from reportify.core.db import create_engine, create_session_factory
from reportify.modules.connectors.base import ConnectorRegistry
from reportify.modules.connectors.data_source_service import DataSourceService
from reportify.modules.connectors.metadata import MetadataService
from reportify.modules.connectors.profiling import ProfilingService
from reportify.modules.security.secrets import SecretService
from tests.support import scripted_model

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv("REPORTIFY_TEST_DATABASE_URL")


def _database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("REPORTIFY_TEST_DATABASE_URL is not set")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def prepared_database():
    database_url = _database_url()
    previous_url = os.environ.get("REPORTIFY_DATABASE_URL")
    previous_key = os.environ.get("REPORTIFY_SECRET_KEY")

    os.environ["REPORTIFY_DATABASE_URL"] = database_url
    os.environ["REPORTIFY_SECRET_KEY"] = "test-secret"
    get_settings.cache_clear()

    config = AlembicConfig(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(REPO_ROOT / "src" / "reportify" / "db" / "migrations"),
    )
    command.upgrade(config, "head")

    # A clean slate keeps list/pagination assertions meaningful; the test
    # database is disposable and rebuilt by the upgrade above.
    async def _truncate() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "TRUNCATE conversation, analysis_task, task_run, run_event, "
                        "message, tool_call_audit, report_ref, tool_definition, "
                        "tool_grant, dataset_snapshot, table_metadata, column_metadata, "
                        "data_source, secret, workspace_audit, schedule, memory "
                        "RESTART IDENTITY CASCADE"
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(_truncate())

    yield

    if previous_url is None:
        os.environ.pop("REPORTIFY_DATABASE_URL", None)
    else:
        os.environ["REPORTIFY_DATABASE_URL"] = previous_url
    if previous_key is None:
        os.environ.pop("REPORTIFY_SECRET_KEY", None)
    else:
        os.environ["REPORTIFY_SECRET_KEY"] = previous_key
    get_settings.cache_clear()


@pytest.fixture
def database_url() -> str:
    return _database_url()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=_database_url(),
        secret_key="test-secret",
        workspace_dir=Path("examples/workspace"),
        reports_dir=tmp_path / "reports",
        # The tick loop is exercised explicitly; a live loop would race the tests.
        scheduler_enabled=False,
    )


@pytest.fixture
async def session_factory(settings: Settings):
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


@pytest.fixture
def secret_service(settings: Settings) -> SecretService:
    return SecretService(settings.secret_key, settings.key_version)


@pytest.fixture
async def registry(session_factory, secret_service: SecretService):
    connectors = ConnectorRegistry(session_factory, secret_service)
    yield connectors
    await connectors.close_all()


@pytest.fixture
def data_source_service(
    session_factory,
    secret_service: SecretService,
    registry: ConnectorRegistry,
) -> DataSourceService:
    return DataSourceService(session_factory, secret_service, registry)


@pytest.fixture
def metadata_service(
    session_factory,
    registry: ConnectorRegistry,
) -> MetadataService:
    return MetadataService(session_factory, registry)


@pytest.fixture
def profiling_service(
    session_factory,
    registry: ConnectorRegistry,
) -> ProfilingService:
    return ProfilingService(session_factory, registry)


@pytest.fixture
def sample_schema():
    database_url = _database_url()
    schema = f"reportify_test_{uuid4().hex[:8]}"

    async def setup() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(
                    text(
                        f'''
                        CREATE TABLE "{schema}".events (
                            id BIGSERIAL PRIMARY KEY,
                            created_at TIMESTAMPTZ NOT NULL,
                            duration NUMERIC(10, 2),
                            status TEXT,
                            note TEXT
                        )
                        '''
                    )
                )
                await connection.execute(
                    text(
                        f'''
                        INSERT INTO "{schema}".events (created_at, duration, status, note)
                        SELECT now() - (i || ' minutes')::interval,
                               10 + (i % 5) * 2.5,
                               CASE WHEN i % 3 = 0 THEN 'error' ELSE 'ok' END,
                               CASE WHEN i % 4 = 0 THEN NULL ELSE 'n' || i END
                        FROM generate_series(1, 20) AS i
                        '''
                    )
                )
        finally:
            await engine.dispose()

    async def teardown() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )
        finally:
            await engine.dispose()

    asyncio.run(setup())
    yield schema
    asyncio.run(teardown())


@pytest.fixture
async def data_source(data_source_service: DataSourceService, sample_schema: str):
    url = make_url(_database_url())
    assert url.username and url.password and url.database
    return await data_source_service.create(
        name=f"ds_{uuid4().hex[:8]}",
        host=url.host or "127.0.0.1",
        port=url.port or 5432,
        database=url.database,
        username=url.username,
        password=url.password,
        ssl_mode="disable",
        options={
            "schema_allowlist": [sample_schema],
            "max_rows": 10_000,
        },
    )


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_factory(settings: Settings):
    """Build API clients driven by a scripted model (never the real LLM)."""
    clients: list[TestClient] = []

    def _factory(steps: list[dict] | None = None, *, model=None, settings_override=None):
        resolved = model if model is not None else scripted_model(steps or [])
        app = create_app(settings_override or settings, model=resolved)
        test_client = TestClient(app)
        test_client.__enter__()
        clients.append(test_client)
        return test_client

    yield _factory
    for test_client in clients:
        test_client.__exit__(None, None, None)


@pytest.fixture
def sync_metadata(database_url: str):
    """Sync metadata on a private event loop, for sync tests using TestClient."""

    def _sync(data_source_id) -> None:
        async def _run() -> None:
            engine = create_async_engine(database_url)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            connectors = ConnectorRegistry(
                factory,
                SecretService(SecretStr("test-secret"), 1),
            )
            try:
                await MetadataService(factory, connectors).sync(data_source_id)
            finally:
                await connectors.close_all()
                await engine.dispose()

        asyncio.run(_run())

    return _sync


@pytest.fixture(autouse=True)
def clean_mcp_state(database_url: str):
    """Keep MCP servers per-test: otherwise every run probes stale endpoints."""
    yield

    async def _cleanup() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("DELETE FROM mcp_server"))
                await connection.execute(
                    text("DELETE FROM tool_definition WHERE kind = 'mcp'")
                )
        finally:
            await engine.dispose()

    try:
        asyncio.run(_cleanup())
    except RuntimeError:
        # An event loop is still running (async test); skip best-effort cleanup.
        pass


@pytest.fixture
def fake_mcp():
    """A real MCP server on a loopback port, stopped after each test."""
    from tests.integration.fake_mcp import FakeMCPServer

    server = FakeMCPServer().start()
    yield server
    server.stop()


@pytest.fixture
def mcp_hub(session_factory, secret_service: SecretService):
    from reportify.modules.mcp.hub import MCPHub

    return MCPHub(
        session_factory,
        secret_service,
        allow_loopback=True,
        connect_timeout=5.0,
        read_timeout=5.0,
    )


@pytest.fixture
def seeded_snapshot(database_url: str):
    """A data source plus one dataset snapshot, for report lineage tests."""
    source_id = uuid4()
    snapshot_id = uuid4()

    async def setup() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO data_source (id, name, type, status, options) "
                        "VALUES (:id, :name, 'postgresql', 'active', '{}'::jsonb)"
                    ),
                    {"id": source_id, "name": f"ds_{uuid4().hex[:8]}"},
                )
                await connection.execute(
                    text(
                        "INSERT INTO dataset_snapshot "
                        "(id, data_source_id, purpose, sql, params, query_fingerprint, "
                        " row_count, columns, filters) "
                        "VALUES (:id, :source, 'analysis', :sql, '{}'::jsonb, :fp, 2, "
                        "        '[]'::jsonb, '{}'::jsonb)"
                    ),
                    {
                        "id": snapshot_id,
                        "source": source_id,
                        "sql": "SELECT status, count(*) FROM events GROUP BY status",
                        "fp": "a" * 64,
                    },
                )
        finally:
            await engine.dispose()

    async def teardown() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM data_source WHERE id = :id"),
                    {"id": source_id},
                )
        finally:
            await engine.dispose()

    asyncio.run(setup())
    yield {"data_source_id": source_id, "snapshot_id": snapshot_id}
    asyncio.run(teardown())
