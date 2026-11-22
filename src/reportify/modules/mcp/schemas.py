"""MCP API models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

AuthType = Literal["none", "bearer"]
RiskLevel = Literal["read", "write", "destructive"]


class MCPOptions(BaseModel):
    read_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    max_result_bytes: int = Field(default=200_000, ge=1_000, le=5_000_000)


class MCPServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    url: str = Field(min_length=1, max_length=2048)
    auth_type: AuthType = "none"
    token: SecretStr | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    options: MCPOptions = Field(default_factory=MCPOptions)
    enabled: bool = True

    @field_validator("headers")
    @classmethod
    def _reject_secret_headers(cls, headers: dict[str, str]) -> dict[str, str]:
        for key in headers:
            if key.lower() in {"authorization", "cookie", "proxy-authorization"}:
                raise ValueError("credentials must be supplied via token, not headers")
        return headers


class MCPServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    auth_type: AuthType | None = None
    token: SecretStr | None = None
    headers: dict[str, str] | None = None
    options: MCPOptions | None = None
    enabled: bool | None = None


class MCPServerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    transport: str
    url: str | None
    auth_type: str
    has_secret: bool = False
    headers: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    enabled: bool
    status: str
    last_tested_at: datetime | None
    last_error: str | None
    protocol_version: str | None
    server_info: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MCPTestResult(BaseModel):
    ok: bool
    status: str
    tool_count: int = 0
    server_info: dict[str, Any] = Field(default_factory=dict)
    protocol_version: str | None = None
    error: str | None = None


class DiscoveryResult(BaseModel):
    server_id: UUID
    tools_discovered: int = 0
    tools_added: int = 0
    tools_updated: int = 0
    tools_removed: int = 0
    schema_changed: list[str] = Field(default_factory=list)
    status: str = "unknown"
    server_info: dict[str, Any] = Field(default_factory=dict)


class MCPToolView(BaseModel):
    id: UUID
    name: str
    model_name: str
    server_id: UUID
    server_slug: str
    display_name: str
    description: str
    risk_level: str
    enabled: bool
    requires_approval: bool
    granted: bool
    risk_acknowledged: bool


class GrantRequest(BaseModel):
    allowed: bool = True
    risk_level: RiskLevel | None = None
    risk_acknowledged: bool = False
