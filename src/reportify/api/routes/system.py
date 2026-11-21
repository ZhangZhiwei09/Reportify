"""Health and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from reportify import __version__
from reportify.api.deps import get_engine
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
