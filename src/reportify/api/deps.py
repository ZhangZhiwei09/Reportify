"""FastAPI dependencies backed by application state."""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from reportify.core.config import Settings


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_engine(request: Request) -> AsyncEngine:
    return request.app.state.engine
