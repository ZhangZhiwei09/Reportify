"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from reportify import __version__
from reportify.api.routes.data_sources import router as data_sources_router
from reportify.api.routes.system import router as system_router
from reportify.core.config import Settings, get_settings
from reportify.core.db import create_engine, create_session_factory
from reportify.core.logging import configure_logging
from reportify.modules.connectors.base import ConnectorRegistry
from reportify.modules.connectors.data_source_service import DataSourceService
from reportify.modules.connectors.errors import DataLayerError
from reportify.modules.connectors.metadata import MetadataService
from reportify.modules.connectors.profiling import ProfilingService
from reportify.modules.security.secrets import SecretService
from reportify.modules.workspace.loader import WorkspaceLoader


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    secret_service = SecretService(settings.secret_key, settings.key_version)
    registry = ConnectorRegistry(session_factory, secret_service)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.secret_service = secret_service
    app.state.connector_registry = registry
    app.state.data_source_service = DataSourceService(
        session_factory,
        secret_service,
        registry,
    )
    app.state.metadata_service = MetadataService(session_factory, registry)
    app.state.profiling_service = ProfilingService(session_factory, registry)
    app.state.workspace = WorkspaceLoader(settings.workspace_dir).load()

    try:
        yield
    finally:
        await registry.close_all()
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="Reportify", version=__version__, lifespan=lifespan)
    app.state.settings = resolved

    @app.exception_handler(DataLayerError)
    async def data_layer_error_handler(
        request: Request,
        exc: DataLayerError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "detail": exc.detail,
                "retryable": exc.retryable,
            },
        )

    app.include_router(system_router)
    app.include_router(data_sources_router)
    return app
