from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from reportify.core.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.getenv("REPORTIFY_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="REPORTIFY_TEST_DATABASE_URL is not set",
)


def test_upgrade_creates_workspace_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    assert TEST_DATABASE_URL is not None

    monkeypatch.setenv("REPORTIFY_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("REPORTIFY_SECRET_KEY", "test-secret")
    get_settings.cache_clear()

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(REPO_ROOT / "src" / "reportify" / "db" / "migrations"),
    )
    command.upgrade(config, "head")

    assert asyncio.run(_table_exists(TEST_DATABASE_URL))


async def _table_exists(url: str) -> bool:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT to_regclass('public.workspace_audit')")
            )
            return result.scalar() is not None
    finally:
        await engine.dispose()
