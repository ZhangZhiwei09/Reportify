from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from reportify.api.sse import format_event, parse_last_event_id
from reportify.core.events import RunEventView


def _event(sequence: int = 3, event_type: str = "tool_call", **payload) -> RunEventView:
    return RunEventView(
        run_id=uuid4(),
        sequence=sequence,
        event_type=event_type,
        payload=payload or {"tool_name": "query_dataset"},
        created_at=datetime.now(UTC),
    )


def test_format_event_frame() -> None:
    frame = format_event(_event())
    assert frame.startswith("id: 3\nevent: tool_call\ndata: ")
    assert frame.endswith("\n\n")


def test_format_event_keeps_utf8_readable() -> None:
    frame = format_event(_event(summary="查询完成"))
    assert "查询完成" in frame
    assert "\\u" not in frame


def test_parse_last_event_id() -> None:
    assert parse_last_event_id("42") == 42
    assert parse_last_event_id(" 7 ") == 7
    assert parse_last_event_id(None) == 0
    assert parse_last_event_id("") == 0


def test_parse_last_event_id_rejects_garbage() -> None:
    assert parse_last_event_id("abc") == 0
    assert parse_last_event_id("-5") == 0
