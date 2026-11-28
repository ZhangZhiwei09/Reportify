"""Health, readiness and capability endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from reportify import __version__
from reportify.api.deps import get_app_settings, get_engine
from reportify.core.config import Settings
from reportify.core.db import check_database

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/ready")
async def ready(engine: AsyncEngine = Depends(get_engine)) -> JSONResponse:
    database_ok = await check_database(engine)
    return JSONResponse(
        status_code=200 if database_ok else 503,
        content={"status": "ready" if database_ok else "not_ready"},
    )


@router.get("/config")
async def config(
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> dict[str, Any]:
    """Non-sensitive capabilities; never returns a secret value (07 §5.5)."""
    return {
        "version": __version__,
        "app_env": settings.app_env,
        "model": {
            "configured": settings.model_configured,
            "name": settings.deepseek_model,
        },
        "auth_required": settings.auth_token is not None,
        "features": {
            "mcp": True,
            "skills": True,
            "report_templates": True,
            "reports": True,
            "approvals": True,
            "scheduler": True,
            "memory": True,
        },
        "limits": {
            "run_request_limit": settings.run_request_limit,
            "run_tool_calls_limit": settings.run_tool_calls_limit,
            "run_total_tokens_limit": settings.run_total_tokens_limit,
            "run_timeout_seconds": settings.run_timeout_seconds,
            "max_concurrent_runs": settings.max_concurrent_runs,
            "max_prompt_chars": settings.max_prompt_chars,
        },
        "mcp": {
            "allow_loopback": settings.allow_loopback,
            "read_timeout_seconds": settings.mcp_read_timeout_seconds,
        },
        "scheduler": {
            "loop_enabled": settings.scheduler_enabled,
            "tick_seconds": settings.scheduler_tick_seconds,
        },
        "memory": {
            "enabled": settings.memory_enabled,
            "max_items": settings.memory_max_items,
        },
    }
