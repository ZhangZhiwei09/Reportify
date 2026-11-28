"""FastAPI dependencies backed by application state."""

from __future__ import annotations

from secrets import compare_digest

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from reportify.core.config import Settings
from reportify.core.events import EventPublisher
from reportify.modules.connectors.base import ConnectorRegistry
from reportify.modules.connectors.data_source_service import DataSourceService
from reportify.modules.connectors.metadata import MetadataService
from reportify.modules.connectors.profiling import ProfilingService
from reportify.modules.conversation.service import ConversationService
from reportify.modules.mcp.hub import MCPHub
from reportify.modules.mcp.runtime import MCPRuntime
from reportify.modules.reports.service import ReportService
from reportify.modules.reports.templates import ReportTemplateService
from reportify.modules.runtime.runtime import AgentRuntime
from reportify.modules.scheduler.service import SchedulerService
from reportify.modules.security.secrets import SecretService
from reportify.modules.skills.service import SkillService
from reportify.modules.tools.registry import ToolRegistry
from reportify.modules.workspace.service import WorkspaceService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_engine(request: Request) -> AsyncEngine:
    return request.app.state.engine


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def get_secret_service(request: Request) -> SecretService:
    return request.app.state.secret_service


def get_connector_registry(request: Request) -> ConnectorRegistry:
    return request.app.state.connector_registry


def get_data_source_service(request: Request) -> DataSourceService:
    return request.app.state.data_source_service


def get_metadata_service(request: Request) -> MetadataService:
    return request.app.state.metadata_service


def get_profiling_service(request: Request) -> ProfilingService:
    return request.app.state.profiling_service


def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service


def get_runtime(request: Request) -> AgentRuntime:
    return request.app.state.runtime


def get_event_publisher(request: Request) -> EventPublisher:
    return request.app.state.event_publisher


def get_scheduler(request: Request) -> SchedulerService:
    return request.app.state.scheduler


def get_tool_registry(request: Request) -> ToolRegistry:
    return request.app.state.tool_registry


def get_report_service(request: Request) -> ReportService:
    return request.app.state.report_service


def get_mcp_hub(request: Request) -> MCPHub:
    return request.app.state.mcp_hub


def get_mcp_runtime(request: Request) -> MCPRuntime:
    return request.app.state.mcp_runtime


def get_skill_service(request: Request) -> SkillService:
    return request.app.state.skill_service


def get_template_service(request: Request) -> ReportTemplateService:
    return request.app.state.template_service


def get_workspace_service(request: Request) -> WorkspaceService:
    return request.app.state.workspace_service


def require_auth(
    settings: Settings = Depends(get_app_settings),
    authorization: str | None = Header(default=None),
) -> None:
    token = settings.auth_token
    if token is None:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    provided = authorization.removeprefix("Bearer ").strip()
    if not compare_digest(provided, token.get_secret_value()):
        raise HTTPException(status_code=401, detail="invalid bearer token")
