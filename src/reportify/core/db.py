"""Async database engine and session helpers."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from reportify.core.config import Settings

logger = logging.getLogger(__name__)


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_dsn,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def check_database(engine: AsyncEngine) -> bool:
    """Return True when a trivial query succeeds."""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("database readiness check failed", exc_info=True)
        return False
    return True
