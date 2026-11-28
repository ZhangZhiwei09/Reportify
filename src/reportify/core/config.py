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

    # Model access. Missing key is allowed: the app starts and runs fail with
    # a structured `model_not_configured` error instead of crashing at boot.
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    # Run budgets. See docs/architecture/02-agent-runtime.md §9.1.
    run_timeout_seconds: int = 900
    run_request_limit: int = 40
    run_tool_calls_limit: int = 25
    run_total_tokens_limit: int = 300_000
    run_tool_timeout_seconds: int = 120
    max_concurrent_runs: int = 4
    instructions_char_budget: int = 28_000
    max_prompt_chars: int = 20_000

    # MCP. ``ssrf_allow_loopback`` defaults to on outside prod so a local fake
    # server can be used; production deployments must keep it off.
    ssrf_allow_loopback: bool | None = None
    mcp_connect_timeout_seconds: float = 30.0
    mcp_read_timeout_seconds: float = 60.0
    mcp_probe_timeout_seconds: float = 5.0

    # Scheduler (M8). The tick loop claims due rows with SKIP LOCKED, so it is
    # safe to leave enabled on every instance; tests switch it off to stay
    # deterministic.
    scheduler_enabled: bool = True
    scheduler_tick_seconds: float = 15.0
    scheduler_batch_size: int = 10

    # Observability. Unset means tracing is a no-op (09 §10).
    otel_exporter_otlp_endpoint: str | None = None

    @property
    def allow_loopback(self) -> bool:
        if self.ssrf_allow_loopback is not None:
            return self.ssrf_allow_loopback
        return self.app_env in {"dev", "test"}

    @property
    def database_dsn(self) -> str:
        """Return the database URL as a plain string for SQLAlchemy/Alembic."""
        return str(self.database_url)

    @property
    def model_configured(self) -> bool:
        return self.deepseek_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()
