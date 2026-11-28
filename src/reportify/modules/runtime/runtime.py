"""AgentRuntime: the run lifecycle (02 §7, §9, §11, §12).

The runtime is an orchestrator. It assembles context, exposes authorized tools,
pumps PydanticAI events into ``run_event``/``tool_call_audit``, enforces budgets,
and converges every exit path to a persisted terminal state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    CancellationToken,
    DeferredToolRequests,
    DeferredToolResults,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartStartEvent,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import ModelMessagesTypeAdapter, RetryPromptPart, ToolReturnPart
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import UsageLimits
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.core.config import Settings
from reportify.core.errors import Conflict, ConversationBusy, ModelNotConfigured, NotFound
from reportify.core.events import EventPublisher
from reportify.core.telemetry import run_span
from reportify.db.models import Message
from reportify.db.repositories import conversations as conversations_repo
from reportify.db.repositories import tasks as tasks_repo
from reportify.db.repositories import tools as tools_repo
from reportify.modules.connectors.base import ConnectorRegistry
from reportify.modules.connectors.metadata import MetadataService
from reportify.modules.connectors.profiling import ProfilingService
from reportify.modules.mcp.runtime import MCPRuntime, MCPToolsetBundle
from reportify.modules.reports.service import ReportService
from reportify.modules.runtime.context import ContextAssembler
from reportify.modules.runtime.schemas import (
    Budget,
    PendingApproval,
    ResumeState,
    RunOutcome,
    RunRequest,
    RuntimeDeps,
)
from reportify.modules.tools.builtin import BUILTIN_FUNCTIONS
from reportify.modules.tools.registry import ToolRegistry
from reportify.modules.tools.schemas import ToolResult
from reportify.modules.workspace.loader import WorkspaceLoader

logger = logging.getLogger(__name__)

LOOP_FINGERPRINT_LIMIT = 3
MAX_REDACTION_DEPTH = 4
SENSITIVE_KEY_HINTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "dsn",
    "api_key",
    "apikey",
    "authorization",
    "credential",
)
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


class RunLoopDetected(RuntimeError):
    """Raised from the event pump to abort a run stuck in a tool loop."""


class AgentRuntime:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        registry: ToolRegistry,
        connectors: ConnectorRegistry,
        metadata: MetadataService,
        profiling: ProfilingService,
        reports: ReportService,
        workspace_loader: WorkspaceLoader,
        assembler: ContextAssembler,
        events: EventPublisher,
        agent: Agent[RuntimeDeps, str] | None,
        mcp: MCPRuntime | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._registry = registry
        self._connectors = connectors
        self._metadata = metadata
        self._profiling = profiling
        self._reports = reports
        self._workspace_loader = workspace_loader
        self._assembler = assembler
        self._events = events
        self._agent = agent
        self._mcp = mcp
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_runs))
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._outcomes: dict[UUID, RunOutcome] = {}
        self._tokens: dict[UUID, CancellationToken] = {}
        self._conversation_locks: dict[UUID, asyncio.Lock] = {}

    # ------------------------------------------------------------------ API

    async def start(self, request: RunRequest) -> UUID:
        """Persist a queued run and start executing it in the background."""
        if self._agent is None:
            raise ModelNotConfigured()

        lock = self._conversation_locks.setdefault(request.conversation_id, asyncio.Lock())
        async with lock:
            async with self._session_factory() as session:
                task = await tasks_repo.get_task(session, request.task_id)
                if task is None or task.conversation_id != request.conversation_id:
                    raise NotFound(f"task not found in conversation: {request.task_id}")
                active = await tasks_repo.active_run(session, request.conversation_id)
                if active is not None:
                    raise ConversationBusy(
                        f"conversation already has an active run: {active.id}"
                    )
                run = await tasks_repo.create_run(
                    session,
                    task_id=task.id,
                    conversation_id=request.conversation_id,
                    model_name=self._settings.deepseek_model,
                    trigger=request.trigger,
                    limits=self._budget(request.trigger).as_dict(),
                    model_settings=dict(request.model_overrides),
                )
                await tasks_repo.set_task_status(
                    session,
                    task.id,
                    status="planning",
                    current_run_id=run.id,
                )

        self._outcomes.pop(run.id, None)
        self._tasks[run.id] = asyncio.create_task(
            self._execute(run.id, request),
            name=f"run-{run.id}",
        )
        return run.id

    async def wait(self, run_id: UUID, *, wait_seconds: float | None = None) -> RunOutcome:
        """Await a run's outcome. Used by tests and ARQ jobs, not by the API."""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait_seconds)
        outcome = self._outcomes.get(run_id)
        if outcome is None:
            raise NotFound(f"run outcome not available: {run_id}")
        return outcome

    async def cancel(self, run_id: UUID) -> str:
        """Request cancellation; idempotent. Returns the resulting status."""
        async with self._session_factory() as session:
            run = await tasks_repo.request_cancel(session, run_id)
            if run is None:
                raise NotFound(f"run not found: {run_id}")
            if run.status in TERMINAL_RUN_STATUSES:
                return run.status

        token = self._tokens.get(run_id)
        if token is not None:
            token.cancel()
        task = self._tasks.get(run_id)
        if task is not None:
            task.cancel()
        return "cancelling"

    async def recover_stale_runs(self) -> int:
        """Mark runs abandoned by a crashed process as failed (05 §9)."""
        cutoff = datetime.now(UTC) - timedelta(
            seconds=self._settings.run_timeout_seconds + 60
        )
        async with self._session_factory() as session:
            stale = await tasks_repo.stale_active_runs(session, started_before=cutoff)
            if not stale:
                return 0
            for run in stale:
                await tasks_repo.finish_run(
                    session,
                    run.id,
                    status="failed",
                    error={
                        "code": "stale_run",
                        "detail": "run was left running by a previous process",
                    },
                )
                await tasks_repo.set_task_status(
                    session,
                    run.task_id,
                    status="failed",
                    error={"code": "stale_run", "detail": "previous run did not finish"},
                )
        for run in stale:
            await self._events.publish(
                run.id,
                "error",
                {"code": "stale_run", "status": "failed"},
            )
            logger.warning("marked stale run failed", extra={"run_id": str(run.id)})
        return len(stale)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def has_active_run(self, conversation_id: UUID) -> bool:
        """Cheap pre-check so the API can answer 409 before persisting a message."""
        async with self._session_factory() as session:
            return await tasks_repo.active_run(session, conversation_id) is not None

    async def get_run(self, run_id: UUID):
        async with self._session_factory() as session:
            run = await tasks_repo.get_run(session, run_id)
        if run is None:
            raise NotFound(f"run not found: {run_id}")
        return run

    # ------------------------------------------------------------- execution

    def _budget(self, trigger: str) -> Budget:
        if trigger == "scheduled":
            return Budget(
                request_limit=self._settings.run_request_limit * 2,
                tool_calls_limit=self._settings.run_tool_calls_limit * 2,
                total_tokens_limit=self._settings.run_total_tokens_limit * 2,
                timeout_seconds=self._settings.run_timeout_seconds * 3,
                tool_timeout_seconds=self._settings.run_tool_timeout_seconds,
            )
        return Budget(
            request_limit=self._settings.run_request_limit,
            tool_calls_limit=self._settings.run_tool_calls_limit,
            total_tokens_limit=self._settings.run_total_tokens_limit,
            timeout_seconds=self._settings.run_timeout_seconds,
            tool_timeout_seconds=self._settings.run_tool_timeout_seconds,
        )

    async def _execute(
        self,
        run_id: UUID,
        request: RunRequest | None,
        *,
        resume: ResumeState | None = None,
    ) -> None:
        with run_span(run_id, self._settings.deepseek_model) as span:
            outcome = await self._execute_outcome(run_id, request, resume=resume)
        span.set_status(outcome.status)
        if outcome.error:
            span.record_error(str(outcome.error.get("code", "error")))
        self._outcomes[run_id] = outcome
        self._tasks.pop(run_id, None)

    async def _execute_outcome(
        self,
        run_id: UUID,
        request: RunRequest | None,
        *,
        resume: ResumeState | None = None,
    ) -> RunOutcome:
        try:
            return await self._run(run_id, request, resume=resume)
        except asyncio.CancelledError:
            return await self._finish_cancelled(run_id)
        except RunLoopDetected as exc:
            return await self._finish_error(
                run_id, code="loop_detected", detail=str(exc), status="failed"
            )
        except ModelNotConfigured as exc:
            return await self._finish_error(
                run_id, code="model_not_configured", detail=exc.detail, status="failed"
            )
        except UsageLimitExceeded as exc:
            return await self._finish_error(
                run_id, code="budget_exceeded", detail=str(exc), status="failed"
            )
        except TimeoutError:
            return await self._finish_error(
                run_id,
                code="run_timeout",
                detail="run exceeded its timeout",
                status="timed_out",
            )
        except UnexpectedModelBehavior as exc:
            return await self._finish_error(
                run_id,
                code="unexpected_model_behavior",
                detail=str(exc),
                status="failed",
            )
        except Exception as exc:  # noqa: BLE001 - every path must persist
            logger.exception("run failed", extra={"run_id": str(run_id)})
            return await self._finish_error(
                run_id,
                code="internal_error",
                detail=f"{type(exc).__name__}: {exc}",
                status="failed",
            )
        finally:
            self._tokens.pop(run_id, None)

    async def _run(
        self,
        run_id: UUID,
        request: RunRequest | None,
        *,
        resume: ResumeState | None = None,
    ) -> RunOutcome:
        agent = self._agent
        if agent is None:
            raise ModelNotConfigured()

        async with self._session_factory() as session:
            run = await tasks_repo.get_run(session, run_id)
            if run is None:
                raise NotFound(f"run not found: {run_id}")
            task = await tasks_repo.get_task(session, run.task_id)
            if task is None:
                raise NotFound(f"task not found: {run.task_id}")
            user_prompt: str | None = None
            if request is not None:
                message = await session.get(Message, request.user_message_id)
                user_prompt = message.content if message is not None else task.goal

        await self._mark_running(run_id)
        budget = self._budget(run.trigger)
        if resume is None:
            await self._events.publish(
                run_id,
                "run_started",
                {
                    "model": self._settings.deepseek_model,
                    "task_id": str(task.id),
                    "conversation_id": str(task.conversation_id),
                    "trigger": run.trigger,
                    "limits": budget.as_dict(),
                },
            )
        else:
            await self._set_task_status(task.id, status="running", current_run_id=run_id)
            async with self._session_factory() as session:
                await tasks_repo.clear_pending_approvals(session, run_id)

        workspace = self._workspace_loader.load()
        bundle = await self._assembler.build(task, workspace)
        specs = await self._registry.list_for_run(
            task_id=task.id,
            conversation_id=task.conversation_id,
        )
        tools = [
            BUILTIN_FUNCTIONS[spec.model_name]
            for spec in specs
            if spec.model_name in BUILTIN_FUNCTIONS
        ]
        approval_names = {
            spec.model_name
            for spec in specs
            if spec.requires_approval or spec.risk_level == "destructive"
        }
        risk_by_name = {spec.model_name: spec.risk_level for spec in specs}
        toolset = self._gate_approvals(FunctionToolset(tools=tools), approval_names)

        mcp_bundle = (
            await self._mcp.toolsets(specs)
            if self._mcp is not None
            else MCPToolsetBundle()
        )
        if approval_names:
            mcp_bundle.toolsets = [
                mcp_toolset.approval_required(
                    lambda ctx, tool_definition, args: (  # noqa: ANN001
                        getattr(tool_definition, "name", "") in approval_names
                    )
                )
                for mcp_toolset in mcp_bundle.toolsets
            ]
        warnings = list(bundle.warnings)
        if mcp_bundle.unavailable:
            warnings.append(
                "mcp servers unreachable this run: " + ", ".join(mcp_bundle.unavailable)
            )
            logger.warning(
                "mcp servers unavailable",
                extra={"run_id": str(run_id), "servers": mcp_bundle.unavailable},
            )
        if mcp_bundle.skipped:
            warnings.append(
                "mcp servers disabled or in error: " + ", ".join(mcp_bundle.skipped)
            )

        if resume is None:
            await self._events.publish(
                run_id,
                "plan",
                {
                    "goal": task.goal,
                    "skill_names": list(task.skill_names),
                    "template_name": task.template_name,
                    "tools": [spec.model_name for spec in specs],
                    "warnings": warnings,
                    "mcp_servers": [
                        spec.source_slug for spec in specs if spec.kind == "mcp"
                    ],
                    "mcp_unavailable": mcp_bundle.unavailable,
                    "approval_required_tools": sorted(approval_names),
                    "budget": budget.as_dict(),
                },
            )
            await self._append_message(
                task.conversation_id,
                role="system",
                message_type="analysis_plan",
                content="已生成执行计划。",
                payload={"goal": task.goal, "tools": [spec.model_name for spec in specs]},
                task_id=task.id,
                run_id=run_id,
            )
        await self._set_task_status(task.id, status="running", current_run_id=run_id)

        deps = RuntimeDeps(
            run_id=run_id,
            task_id=task.id,
            conversation_id=task.conversation_id,
            session_factory=self._session_factory,
            registry=self._registry,
            connectors=self._connectors,
            metadata=self._metadata,
            profiling=self._profiling,
            reports=self._reports,
            workspace=workspace,
            workspace_loader=self._workspace_loader,
            events=self._events,
        )
        limits = UsageLimits(
            request_limit=budget.request_limit,
            tool_calls_limit=budget.tool_calls_limit,
            total_tokens_limit=budget.total_tokens_limit,
        )
        token = CancellationToken()
        self._tokens[run_id] = token
        pump = _EventPump(self, run_id)

        result = None
        stream_kwargs: dict[str, Any] = {
            "deps": deps,
            "instructions": bundle.instructions,
            "toolsets": [toolset, *mcp_bundle.toolsets],
            "usage_limits": limits,
            "cancellation_token": token,
            "timeout": float(budget.timeout_seconds),
        }
        if resume is None:
            stream_kwargs["user_prompt"] = user_prompt
            stream_kwargs["message_history"] = bundle.message_history
        else:
            stream_kwargs["message_history"] = resume.message_history
            stream_kwargs["deferred_tool_results"] = DeferredToolResults(
                approvals={
                    item["tool_call_id"]: item.get("decision") == "approved"
                    for item in resume.approvals
                }
            )

        async with self._semaphore:
            async with agent.run_stream_events(**stream_kwargs) as events:
                async for event in events:
                    if isinstance(event, AgentRunResultEvent):
                        result = event.result
                    await pump.handle(event)

        if result is None:
            raise RuntimeError("agent finished without a result event")

        usage = _usage_dict(result.usage)
        await self._events.publish(run_id, "usage", usage)

        if isinstance(result.output, DeferredToolRequests):
            return await self._defer_for_approval(
                run_id,
                task,
                result,
                specs=specs,
                risk_by_name=risk_by_name,
                usage=usage,
                history_blob=json.loads(result.all_messages_json()),
            )

        output = result.output if isinstance(result.output, str) else str(result.output)
        await self._append_message(
            task.conversation_id,
            role="assistant",
            message_type="assistant_message",
            content=output,
            payload={"usage": usage},
            task_id=task.id,
            run_id=run_id,
        )
        report_id = deps.report_state.report_id
        if report_id is not None:
            await self._append_message(
                task.conversation_id,
                role="system",
                message_type="report_event",
                content="已生成报告。",
                payload={"report_ref_id": str(report_id), "renderer": "echarts-v1"},
                task_id=task.id,
                run_id=run_id,
            )
        # Task settles before the run's terminal status, so any client that sees
        # a terminal run can trust the task state too.
        await self._set_task_status(
            task.id,
            status="completed",
            current_run_id=run_id,
            completed=True,
        )
        await self._finish_run(
            run_id,
            status="succeeded",
            usage=usage,
            history_blob=json.loads(result.all_messages_json()),
        )
        await self._events.publish(
            run_id,
            "run_completed",
            {
                "status": "succeeded",
                "usage": usage,
                "report_ref_id": str(report_id) if report_id else None,
                "output_preview": output[:500],
            },
        )
        return RunOutcome(
            run_id=run_id,
            status="succeeded",
            output=output,
            usage=usage,
            report_ref_id=report_id,
        )

    # -------------------------------------------------------------- approvals

    @staticmethod
    def _gate_approvals(toolset: Any, approval_names: set[str]) -> Any:
        """Wrap a toolset so matching calls pause for a human decision."""
        if not approval_names:
            return toolset
        return toolset.approval_required(
            lambda ctx, tool_definition, args: (  # noqa: ANN001 - SDK signature
                getattr(tool_definition, "name", "") in approval_names
            )
        )

    async def _defer_for_approval(
        self,
        run_id: UUID,
        task: Any,
        result: Any,
        *,
        specs: list[Any],
        risk_by_name: dict[str, str],
        usage: dict[str, Any],
        history_blob: list[Any],
    ) -> RunOutcome:
        requests = result.output
        approvals = [
            PendingApproval(
                approval_id=part.tool_call_id,
                tool_call_id=part.tool_call_id,
                tool_name=part.tool_name,
                args_redacted=_redact(part.args if isinstance(part.args, dict) else {}),
                risk=risk_by_name.get(part.tool_name, "write"),
            ).model_dump(mode="json")
            for part in requests.approvals
        ]
        async with self._session_factory() as session:
            await tasks_repo.mark_waiting_approval(
                session,
                run_id,
                approvals=approvals,
                history_blob=history_blob,
            )
            await tasks_repo.set_usage(session, run_id, usage)
        await self._set_task_status(
            task.id,
            status="waiting_approval",
            current_run_id=run_id,
        )
        for item in approvals:
            await self._events.publish(
                run_id,
                "approval_required",
                {
                    "approval_id": item["approval_id"],
                    "tool_call_id": item["tool_call_id"],
                    "tool_name": item["tool_name"],
                    "risk": item["risk"],
                    "args_redacted": item["args_redacted"],
                },
            )
        await self._append_message(
            task.conversation_id,
            role="system",
            message_type="system_event",
            content="等待审批：" + ", ".join(item["tool_name"] for item in approvals),
            payload={"approvals": approvals, "run_id": str(run_id)},
            task_id=task.id,
            run_id=run_id,
        )
        return RunOutcome(run_id=run_id, status="waiting_approval", usage=usage)

    async def get_pending_approvals(self, run_id: UUID) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            run = await tasks_repo.get_run(session, run_id)
        if run is None:
            raise NotFound(f"run not found: {run_id}")
        return list(run.pending_approvals or [])

    async def decide(self, run_id: UUID, approval_id: str, *, approved: bool) -> dict[str, Any]:
        """Record one decision and resume the run once every call is decided."""
        async with self._session_factory() as session:
            run = await tasks_repo.get_run(session, run_id)
            if run is None:
                raise NotFound(f"run not found: {run_id}")
            if run.status != "waiting_approval":
                raise Conflict(f"run is not waiting for approval: {run.status}")
            stored = list(run.history_blob or [])
            try:
                history = ModelMessagesTypeAdapter.validate_python(stored)
            except Exception as exc:  # noqa: BLE001 - corrupt history is a conflict
                raise Conflict(
                    "stored message history is unreadable; start a new run"
                ) from exc
            recorded = await tasks_repo.record_approval_decision(
                session,
                run_id,
                approval_id,
                approved=approved,
            )
        if recorded is None:
            raise NotFound(f"approval not found: {approval_id}")
        approvals, all_decided = recorded

        if not all_decided:
            return {
                "run_id": str(run_id),
                "status": "waiting_approval",
                "approvals": approvals,
            }

        resume = ResumeState(message_history=history, approvals=approvals)
        self._outcomes.pop(run_id, None)
        self._tasks[run_id] = asyncio.create_task(
            self._execute(run_id, None, resume=resume),
            name=f"run-{run_id}-resume",
        )
        return {"run_id": str(run_id), "status": "resuming", "approvals": approvals}

    # -------------------------------------------------------------- terminal

    async def _finish_cancelled(self, run_id: UUID) -> RunOutcome:
        await self._mark_task(run_id, status="cancelled")
        await self._finish_run(run_id, status="cancelled")
        await self._events.publish(run_id, "run_completed", {"status": "cancelled"})
        return RunOutcome(run_id=run_id, status="cancelled")

    async def _finish_error(
        self,
        run_id: UUID,
        *,
        code: str,
        detail: str,
        status: str,
    ) -> RunOutcome:
        error = {"code": code, "detail": detail}
        await self._mark_task(run_id, status="failed", error=error)
        await self._finish_run(run_id, status=status, error=error)
        await self._events.publish(
            run_id,
            "error",
            {"code": code, "detail": detail, "status": status},
        )
        return RunOutcome(run_id=run_id, status=status, error=error)

    async def _mark_task(
        self,
        run_id: UUID,
        *,
        status: str,
        error: dict[str, Any] | None = None,
    ) -> None:
        async with self._session_factory() as session:
            run = await tasks_repo.get_run(session, run_id)
        if run is None:
            return
        await self._set_task_status(
            run.task_id,
            status=status,
            current_run_id=run_id,
            error=error,
        )
        if status == "cancelled":
            await self._append_message(
                run.conversation_id,
                role="system",
                message_type="system_event",
                content="运行已取消。",
                payload={"run_id": str(run_id), "status": status},
                task_id=run.task_id,
                run_id=run_id,
            )

    # -------------------------------------------------- persistence helpers

    async def _mark_running(self, run_id: UUID) -> None:
        async with self._session_factory() as session:
            await tasks_repo.mark_running(session, run_id)

    async def _finish_run(self, run_id: UUID, **kwargs: Any) -> None:
        async with self._session_factory() as session:
            await tasks_repo.finish_run(session, run_id, **kwargs)

    async def _set_task_status(self, task_id: UUID, **kwargs: Any) -> None:
        async with self._session_factory() as session:
            await tasks_repo.set_task_status(session, task_id, **kwargs)

    async def _append_message(self, conversation_id: UUID, **kwargs: Any) -> None:
        async with self._session_factory() as session:
            await conversations_repo.append_message(session, conversation_id, **kwargs)

    async def _write_audit(self, **kwargs: Any) -> None:
        async with self._session_factory() as session:
            await tools_repo.write_audit(session, **kwargs)


class _EventPump:
    """Translates PydanticAI events into persisted application events."""

    def __init__(self, runtime: AgentRuntime, run_id: UUID) -> None:
        self._runtime = runtime
        self._run_id = run_id
        self._fingerprints: dict[str, int] = {}
        self._calls: dict[str, tuple[str, dict[str, Any], float]] = {}
        self._requests = 0

    async def handle(self, event: Any) -> None:
        if isinstance(event, FunctionToolCallEvent):
            await self._on_call(event)
        elif isinstance(event, FunctionToolResultEvent):
            await self._on_result(event)
        elif isinstance(event, PartStartEvent) and event.index == 0:
            self._requests += 1
            await self._runtime._events.publish(
                self._run_id,
                "model_request",
                {"request_index": self._requests},
            )

    async def _on_call(self, event: FunctionToolCallEvent) -> None:
        part = event.part
        args = part.args if isinstance(part.args, dict) else {}
        redacted = _redact(args)
        self._calls[part.tool_call_id] = (part.tool_name, redacted, time.monotonic())

        key = _fingerprint(part.tool_name, args)
        count = self._fingerprints.get(key, 0) + 1
        self._fingerprints[key] = count

        await self._runtime._events.publish(
            self._run_id,
            "tool_call",
            {
                "tool_call_id": part.tool_call_id,
                "tool_name": part.tool_name,
                "args_redacted": redacted,
                "status": "started",
                "repeat": count,
            },
        )
        if count >= LOOP_FINGERPRINT_LIMIT:
            raise RunLoopDetected(
                f"tool {part.tool_name} called {count} times with identical arguments"
            )

    async def _on_result(self, event: FunctionToolResultEvent) -> None:
        part = event.part
        # ``event.content`` is supplementary user content for the next request;
        # the tool's own return value lives on the part.
        content = getattr(part, "content", None)
        tool_name = getattr(part, "tool_name", None) or "unknown"
        tool_call_id = getattr(part, "tool_call_id", None)
        _, args_redacted, started = self._calls.pop(
            tool_call_id,
            (tool_name, {}, time.monotonic()),
        )
        duration_ms = int((time.monotonic() - started) * 1000)

        if isinstance(content, ToolResult):
            status = "succeeded" if content.ok else "failed"
            error_code = content.error.code if content.error else None
            summary: dict[str, Any] = {
                "ok": content.ok,
                "summary": content.summary[:500],
                "truncated": content.truncated,
            }
            if content.data:
                summary["row_count"] = content.data.get("row_count")
                if content.data.get("snapshot_id"):
                    summary["snapshot_id"] = content.data["snapshot_id"]
        elif isinstance(part, RetryPromptPart):
            text = str(content)
            if "timed out" in text.lower():
                status, error_code = "timeout", "timeout"
            else:
                status, error_code = "failed", "tool_error"
            summary = {"ok": False, "summary": text[:500]}
        elif isinstance(part, ToolReturnPart):
            text = str(content)
            if text.startswith("Unknown tool name"):
                # The SDK turns an unavailable tool into a model-visible result;
                # nothing executed, so it is a denial, not a success.
                status, error_code = "denied", "unknown_tool"
            elif "tool call was denied" in text.lower():
                status, error_code = "rejected", "approval_rejected"
            elif "timed out" in text.lower():
                status, error_code = "timeout", "timeout"
            else:
                status, error_code = "succeeded", None
            summary = {"ok": status == "succeeded", "summary": text[:500]}
        else:
            status, error_code = "failed", "tool_error"
            summary = {"ok": False, "summary": str(content)[:500]}
        summary["duration_ms"] = duration_ms
        source = "mcp" if tool_name.startswith("mcp_") else "builtin"

        await self._runtime._write_audit(
            run_id=self._run_id,
            tool_name=tool_name,
            source=source,
            status=status,
            arguments_redacted=args_redacted,
            result_summary=summary,
            error_code=error_code,
            duration_ms=duration_ms,
        )
        await self._runtime._events.publish(
            self._run_id,
            "tool_result",
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "status": status,
                "duration_ms": duration_ms,
                "summary": summary.get("summary", ""),
                "error_code": error_code,
            },
        )


def _fingerprint(tool_name: str, args: Any) -> str:
    try:
        normalized = json.dumps(args, sort_keys=True, default=str)
    except TypeError:
        normalized = str(args)
    return f"{tool_name}:{normalized}"


def _redact(value: Any, depth: int = 0) -> Any:
    if depth >= MAX_REDACTION_DEPTH:
        return "***"
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(hint in lowered for hint in SENSITIVE_KEY_HINTS):
                redacted[key] = "***"
            else:
                redacted[key] = _redact(item, depth + 1)
        return redacted
    if isinstance(value, list | tuple):
        return [_redact(item, depth + 1) for item in value]
    return value


def _usage_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        data = usage.model_dump()
        return {key: value for key, value in data.items() if value is not None}
    if hasattr(usage, "__dict__"):
        return {
            key: value
            for key, value in vars(usage).items()
            if not key.startswith("_") and value is not None
        }
    return {}
