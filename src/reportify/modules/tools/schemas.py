"""Tool registry contracts and the ToolResult envelope (03 §4, §6)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from reportify.modules.connectors.schemas import Lineage

ToolKind = Literal["builtin_data", "builtin_analysis", "report", "meta", "mcp"]
RiskLevel = Literal["read", "write", "destructive"]
ToolErrorCode = Literal[
    "timeout",
    "permission_denied",
    "invalid_argument",
    "upstream_error",
    "not_found",
    "internal_error",
]

MAX_RESULT_BYTES = 200 * 1024


class ToolSpec(BaseModel):
    """Registry-facing description of one tool."""

    name: str
    model_name: str
    kind: ToolKind
    risk_level: RiskLevel
    requires_approval: bool = False
    display_name: str
    description: str
    arguments: dict[str, str] = Field(default_factory=dict)
    required_arguments: tuple[str, ...] = ()
    # MCP-only metadata; builtin tools leave these empty.
    source_id: UUID | None = None
    source_slug: str | None = None
    model_name_raw: str | None = None

    def input_schema(self) -> dict[str, Any]:
        """Advisory JSON Schema for the registry/UI.

        Runtime validation is the tool function signature; this exists so the
        admin UI and ``tool_definition`` rows can describe arguments without
        importing PydanticAI.
        """
        return {
            "type": "object",
            "properties": {
                key: {"type": value} for key, value in self.arguments.items()
            },
            "required": list(self.required_arguments),
        }


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: Literal[
        "granted",
        "denied",
        "needs_approval",
        "risk_unacknowledged",
        "unknown_tool",
    ]
    effective_scope: Literal["task", "conversation", "global", "none"]


class ToolError(BaseModel):
    code: ToolErrorCode
    message: str


class ToolResult(BaseModel):
    """Envelope returned to the model. Never executable content."""

    ok: bool
    summary: str
    data: dict[str, Any] | None = None
    lineage: Lineage | None = None
    warnings: list[str] = Field(default_factory=list)
    truncated: bool = False
    error: ToolError | None = None

    @model_validator(mode="after")
    def _enforce_size_limit(self) -> ToolResult:
        if self.data is None:
            return self
        encoded = json.dumps(self.data, ensure_ascii=False, default=str)
        if len(encoded.encode("utf-8")) <= MAX_RESULT_BYTES:
            return self
        self.data = {"truncated": True, "reason": "result exceeded 200KB limit"}
        self.truncated = True
        self.warnings.append("result truncated to stay within 200KB")
        return self

    @classmethod
    def failure(
        cls,
        code: ToolErrorCode,
        message: str,
        *,
        summary: str | None = None,
    ) -> ToolResult:
        return cls(
            ok=False,
            summary=summary or message,
            error=ToolError(code=code, message=message),
        )
