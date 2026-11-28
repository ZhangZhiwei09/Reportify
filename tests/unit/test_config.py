from __future__ import annotations

import pytest
from pydantic import ValidationError

from reportify.core.config import Settings, get_settings


def test_settings_load_from_environment(settings: Settings) -> None:
    assert str(settings.database_url).startswith("postgresql+asyncpg://")
    assert settings.secret_key.get_secret_value() == "test-secret"
    assert settings.workspace_dir.name == "workspace"


def test_missing_secret_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "REPORTIFY_DATABASE_URL",
        "postgresql+asyncpg://user:pass@localhost:5432/db",
    )
    monkeypatch.delenv("REPORTIFY_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_get_settings_is_cached(settings_env: None) -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()


def test_scheduler_defaults_are_safe(settings: Settings) -> None:
    assert settings.scheduler_enabled is True
    assert settings.scheduler_tick_seconds >= 1
    assert settings.scheduler_batch_size >= 1
