"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from reportify import __version__
from reportify.api.routes.system import router as system_router
from reportify.core.config import Settings, get_settings
from reportify.core.db import create_engine, create_session_factory
from reportify.core.logging import configure_logging
from reportify.modules.workspace.loader import WorkspaceLoader


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)

    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.workspace = WorkspaceLoader(settings.workspace_dir).load()

    try:
        yield
    finally:
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="Reportify", version=__version__, lifespan=lifespan)
    app.state.settings = resolved
    app.include_router(system_router)
    return app
