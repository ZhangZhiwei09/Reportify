"""Runtime contracts: request, budget, dependencies and outcome."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import ToolFailed
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.core.events import EventPublisher
from reportify.modules.connectors.base import ConnectorRegistry
from reportify.modules.connectors.metadata import MetadataService
from reportify.modules.connectors.profiling import ProfilingService
from reportify.modules.reports.service import ReportService
from reportify.modules.tools.registry import ToolRegistry
from reportify.modules.workspace.loader import WorkspaceLoader
from reportify.modules.workspace.schemas import WorkspaceSnapshot

Trigger = Literal["interactive", "scheduled", "api"]


@dataclass
class ReportState:
    """Per-run report bookkeeping (generate_report is allowed once)."""

    generated: bool = False
    report_id: UUID | None = None


@dataclass
class RuntimeDeps:
    """Everything a tool may touch. Created per run, never shared."""

    run_id: UUID
    task_id: UUID
    conversation_id: UUID
    session_factory: async_sessionmaker[AsyncSession]
    registry: ToolRegistry
    connectors: ConnectorRegistry
    metadata: MetadataService
    profiling: ProfilingService
    reports: ReportService
    workspace: WorkspaceSnapshot
    workspace_loader: WorkspaceLoader
    events: EventPublisher
    report_state: ReportState = field(default_factory=ReportState)

    async def ensure_tool_allowed(self, model_name: str) -> None:
        """Layer 3: re-check authorization at execution time.

        The toolset handed to the model only contains authorized tools; this check
        exists so a grant revoked mid-run cannot still execute (03 §4.3).
        """
        decision = await self.registry.authorize(
            model_name,
            task_id=self.task_id,
            conversation_id=self.conversation_id,
        )
        if not decision.allowed:
            raise ToolFailed(
                f"tool {model_name} is not allowed: {decision.reason}"
            )


@dataclass(frozen=True)
class Budget:
    request_limit: int = 40
    tool_calls_limit: int = 25
    total_tokens_limit: int = 300_000
    timeout_seconds: int = 900
    tool_timeout_seconds: int = 120

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_limit": self.request_limit,
            "tool_calls_limit": self.tool_calls_limit,
            "total_tokens_limit": self.total_tokens_limit,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class RunRequest:
    conversation_id: UUID
    task_id: UUID
    user_message_id: UUID
    trigger: Trigger = "interactive"
    skill_names: tuple[str, ...] = ()
    template_name: str | None = None
    model_overrides: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None


@dataclass
class RunOutcome:
    run_id: UUID
    status: str
    output: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    report_ref_id: UUID | None = None


class PendingApproval(BaseModel):
    """One deferred tool call awaiting a human decision (05 §6.1)."""

    approval_id: str
    tool_call_id: str
    tool_name: str
    args_redacted: dict[str, Any] = Field(default_factory=dict)
    risk: str = "write"
    decision: Literal["pending", "approved", "denied"] = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ResumeState:
    """Everything needed to continue a run that was parked for approval."""

    message_history: list[Any]
    approvals: list[dict[str, Any]]


class ApprovalDecision(BaseModel):
    """User decision for one deferred tool call (07 §5.1)."""

    decision: Literal["approve", "deny"]
    note: str | None = None
