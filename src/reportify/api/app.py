"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic_ai.models import Model

from reportify import __version__
from reportify.api.middleware import SecurityHeadersMiddleware
from reportify.api.routes.conversations import router as conversations_router
from reportify.api.routes.data_sources import router as data_sources_router
from reportify.api.routes.mcp import router as mcp_router
from reportify.api.routes.memory import router as memory_router
from reportify.api.routes.pages import router as pages_router
from reportify.api.routes.report_templates import router as report_templates_router
from reportify.api.routes.reports import router as reports_router
from reportify.api.routes.runs import router as runs_router
from reportify.api.routes.schedules import router as schedules_router
from reportify.api.routes.skills import router as skills_router
from reportify.api.routes.system import router as system_router
from reportify.api.routes.tasks import router as tasks_router
from reportify.api.routes.workspace import router as workspace_router
from reportify.core.config import Settings, get_settings
from reportify.core.db import create_engine, create_session_factory
from reportify.core.errors import ApiError
from reportify.core.events import EventBroker, EventPublisher
from reportify.core.logging import configure_logging
from reportify.core.netenv import ensure_loopback_bypasses_proxy
from reportify.core.telemetry import configure_telemetry
from reportify.modules.connectors.base import ConnectorRegistry
from reportify.modules.connectors.data_source_service import DataSourceService
from reportify.modules.connectors.errors import DataLayerError
from reportify.modules.connectors.metadata import MetadataService
from reportify.modules.connectors.profiling import ProfilingService
from reportify.modules.conversation.service import ConversationService
from reportify.modules.mcp.hub import MCPHub
from reportify.modules.mcp.runtime import MCPRuntime
from reportify.modules.memory.service import MemoryService
from reportify.modules.reports.service import ReportService
from reportify.modules.reports.templates import ReportTemplateService
from reportify.modules.runtime.agent_factory import build_agent, build_model
from reportify.modules.runtime.context import ContextAssembler
from reportify.modules.runtime.runtime import AgentRuntime
from reportify.modules.scheduler.service import SchedulerService
from reportify.modules.security.secrets import SecretService
from reportify.modules.skills.service import SkillService
from reportify.modules.tools.registry import ToolRegistry
from reportify.modules.workspace.loader import WorkspaceLoader
from reportify.modules.workspace.service import WorkspaceService

logger = logging.getLogger(__name__)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PACKAGE_ROOT / "templates"
STATIC_DIR = PACKAGE_ROOT / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    configure_telemetry(settings)
    ensure_loopback_bypasses_proxy()

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    secret_service = SecretService(settings.secret_key, settings.key_version)
    connector_registry = ConnectorRegistry(session_factory, secret_service)
    tool_registry = ToolRegistry(session_factory)
    broker = EventBroker()
    event_publisher = EventPublisher(session_factory, broker)
    report_service = ReportService(session_factory, settings.reports_dir)
    memory_service = MemoryService(session_factory, max_items=settings.memory_max_items)
    workspace_loader = WorkspaceLoader(settings.workspace_dir)
    assembler = ContextAssembler(
        session_factory,
        char_budget=settings.instructions_char_budget,
        memory=memory_service if settings.memory_enabled else None,
        memory_limit=settings.memory_max_items,
    )

    model = app.state.model if app.state.model is not None else build_model(settings)
    agent = build_agent(model, settings) if model is not None else None
    mcp_hub = MCPHub(
        session_factory,
        secret_service,
        allow_loopback=settings.allow_loopback,
        connect_timeout=settings.mcp_connect_timeout_seconds,
        read_timeout=settings.mcp_read_timeout_seconds,
    )
    mcp_runtime = MCPRuntime(
        session_factory,
        secret_service,
        allow_loopback=settings.allow_loopback,
        connect_timeout=settings.mcp_connect_timeout_seconds,
        read_timeout=settings.mcp_read_timeout_seconds,
        probe_timeout=settings.mcp_probe_timeout_seconds,
    )
    runtime = AgentRuntime(
        settings=settings,
        session_factory=session_factory,
        registry=tool_registry,
        connectors=connector_registry,
        metadata=MetadataService(session_factory, connector_registry),
        profiling=ProfilingService(session_factory, connector_registry),
        reports=report_service,
        workspace_loader=workspace_loader,
        assembler=assembler,
        events=event_publisher,
        agent=agent,
        mcp=mcp_runtime,
    )

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.secret_service = secret_service
    app.state.connector_registry = connector_registry
    app.state.tool_registry = tool_registry
    app.state.event_publisher = event_publisher
    app.state.report_service = report_service
    app.state.memory_service = memory_service
    app.state.conversation_service = ConversationService(
        session_factory,
        max_prompt_chars=settings.max_prompt_chars,
    )
    app.state.data_source_service = DataSourceService(
        session_factory,
        secret_service,
        connector_registry,
    )
    app.state.metadata_service = MetadataService(session_factory, connector_registry)
    app.state.profiling_service = ProfilingService(session_factory, connector_registry)
    app.state.workspace = workspace_loader.load()
    app.state.runtime = runtime
    app.state.scheduler = SchedulerService(
        session_factory,
        runtime,
        enabled=settings.scheduler_enabled,
        tick_seconds=settings.scheduler_tick_seconds,
        batch_size=settings.scheduler_batch_size,
    )
    app.state.mcp_hub = mcp_hub
    app.state.mcp_runtime = mcp_runtime
    app.state.skill_service = SkillService(workspace_loader)
    app.state.template_service = ReportTemplateService(workspace_loader)
    app.state.workspace_service = WorkspaceService(workspace_loader, session_factory)

    try:
        await tool_registry.sync_builtins()
        recovered = await runtime.recover_stale_runs()
        if recovered:
            logger.warning("recovered %s stale runs", recovered)
        await app.state.scheduler.start()
        yield
    finally:
        await app.state.scheduler.stop()
        await runtime.shutdown()
        await connector_registry.close_all()
        await engine.dispose()


def create_app(settings: Settings | None = None, *, model: Model | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="Reportify", version=__version__, lifespan=lifespan)
    app.state.settings = resolved
    app.state.model = model
    app.state.templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    app.add_middleware(SecurityHeadersMiddleware)
    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.body(instance=request.url.path),
            headers={"Cache-Control": "no-store"},
        )

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
    app.include_router(conversations_router)
    app.include_router(tasks_router)
    app.include_router(runs_router)
    app.include_router(schedules_router)
    app.include_router(reports_router)
    app.include_router(mcp_router)
    app.include_router(memory_router)
    app.include_router(skills_router)
    app.include_router(report_templates_router)
    app.include_router(workspace_router)
    app.include_router(pages_router)
    return app
