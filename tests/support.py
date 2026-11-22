"""Test support: a deterministic model that scripts tool calls and answers.

``FunctionModel`` needs both ``function`` (for ``run``) and ``stream_function``
(for ``run_stream_events``), so both are generated from the same script. No test
ever calls the real DeepSeek API (09 §8).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

Step = dict[str, Any]


def tool_step(name: str, args: dict[str, Any] | None = None) -> Step:
    return {"tool": name, "args": args or {}}


def text_step(text: str) -> Step:
    return {"text": text}


def _completed_turns(messages: Sequence[ModelMessage]) -> int:
    return sum(
        1
        for message in messages
        for part in getattr(message, "parts", ())
        if isinstance(part, ToolReturnPart | RetryPromptPart)
    )


def scripted_model(steps: Sequence[Step], *, fallback_text: str = "完成。") -> FunctionModel:
    """Return a model that replays ``steps`` one per turn, then answers."""

    def _pick(messages: Sequence[ModelMessage]) -> Step:
        turn = _completed_turns(messages)
        if turn >= len(steps):
            return text_step(fallback_text)
        return steps[turn]

    def function(messages: Sequence[ModelMessage], info: AgentInfo) -> ModelResponse:
        turn = _completed_turns(messages)
        step = _pick(messages)
        if "tool" in step:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=step["tool"],
                        args=step.get("args", {}),
                        tool_call_id=f"call_{turn}",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content=step.get("text", fallback_text))])

    async def stream_function(
        messages: Sequence[ModelMessage],
        info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        turn = _completed_turns(messages)
        step = _pick(messages)
        if "tool" in step:
            yield {
                0: DeltaToolCall(
                    name=step["tool"],
                    json_args=json.dumps(step.get("args", {}), ensure_ascii=False),
                    tool_call_id=f"call_{turn}",
                )
            }
            return
        text = step.get("text", fallback_text)
        for chunk in _chunks(text):
            yield chunk

    return FunctionModel(function, stream_function=stream_function, model_name="scripted")


def _chunks(text: str, size: int = 8) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


def wait_for_run(client, run_id: str, *, timeout: float = 20.0) -> dict[str, Any]:
    """Poll ``GET /runs/{id}`` until the run reaches a terminal status."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in TERMINAL_RUN_STATUSES:
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish within {timeout}s")


def event_names(client, run_id: str) -> list[str]:
    """Event types from the SSE endpoint (replay only; the run is finished)."""
    response = client.get(f"/api/v1/runs/{run_id}/events")
    assert response.status_code == 200, response.text
    return [
        line.removeprefix("event: ").strip()
        for line in response.text.splitlines()
        if line.startswith("event: ")
    ]


def sse_frames(client, run_id: str, *, last_event_id: str | None = None) -> list[tuple[int, str]]:
    headers = {"Last-Event-ID": last_event_id} if last_event_id else {}
    response = client.get(f"/api/v1/runs/{run_id}/events", headers=headers)
    assert response.status_code == 200, response.text
    frames: list[tuple[int, str]] = []
    current_id: int | None = None
    for line in response.text.splitlines():
        if line.startswith("id: "):
            current_id = int(line[4:])
        elif line.startswith("event: ") and current_id is not None:
            frames.append((current_id, line[7:].strip()))
    return frames


def run_sql(database_url: str, query: str, **params: Any) -> list[dict[str, Any]]:
    """Run one read-only query on its own engine; for assertions in sync tests."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _run() -> list[dict[str, Any]]:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as connection:
                rows = await connection.execute(text(query), params)
                return [dict(row._mapping) for row in rows]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def make_send_message(client, conversation_id: str, content: str, **extra: Any) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": content, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()
