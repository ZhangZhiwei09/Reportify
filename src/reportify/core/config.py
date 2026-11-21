"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Secrets have no defaults on purpose: a missing ``REPORTIFY_SECRET_KEY`` must
    fail fast instead of silently using an insecure value.
    """

    model_config = SettingsConfigDict(
        env_prefix="REPORTIFY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["dev", "test", "prod"] = "dev"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    database_url: PostgresDsn
    redis_url: RedisDsn | None = None

    workspace_dir: Path = Path("workspace")
    reports_dir: Path = Path("reports")

    secret_key: SecretStr
    key_version: int = 1
    auth_token: SecretStr | None = None

    @property
    def database_dsn(self) -> str:
        """Return the database URL as a plain string for SQLAlchemy/Alembic."""
        return str(self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
