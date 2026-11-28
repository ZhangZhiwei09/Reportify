from __future__ import annotations

import uuid

from reportify.db.models import ToolGrant
from reportify.modules.tools.registry import (
    BUILTIN_SPECS,
    ToolRegistry,
    select_grant,
)
from reportify.modules.tools.schemas import ToolResult


def _grant(scope: str, scope_id, allowed: bool = True, ack: bool = True) -> ToolGrant:
    return ToolGrant(
        tool_definition_id=uuid.uuid4(),
        scope=scope,
        scope_id=scope_id,
        allowed=allowed,
        risk_acknowledged=ack,
    )


def test_builtin_specs_are_unique_and_named() -> None:
    model_names = [spec.model_name for spec in BUILTIN_SPECS]
    assert len(model_names) == len(set(model_names))
    assert all(spec.name == f"builtin.{spec.model_name}" for spec in BUILTIN_SPECS)


def test_builtin_specs_cover_the_contract() -> None:
    names = {spec.model_name for spec in BUILTIN_SPECS}
    assert names == {
        "inspect_dataset",
        "profile_dataset",
        "query_dataset",
        "fetch_dataset",
        "load_skill",
        "generate_report",
        "analyze_trend",
        "analyze_distribution",
        "compare_periods",
        "detect_anomalies",
        "analyze_correlation",
    }
    risk = {spec.model_name: spec.risk_level for spec in BUILTIN_SPECS}
    assert risk["generate_report"] == "write"
    assert all(risk[name] == "read" for name in risk if name != "generate_report")
    analysis = {spec.model_name for spec in BUILTIN_SPECS if spec.kind == "builtin_analysis"}
    assert analysis == {
        "analyze_trend",
        "analyze_distribution",
        "compare_periods",
        "detect_anomalies",
        "analyze_correlation",
    }


def test_input_schema_only_describes_declared_arguments() -> None:
    spec = next(item for item in BUILTIN_SPECS if item.model_name == "query_dataset")
    schema = spec.input_schema()
    assert schema["type"] == "object"
    assert set(schema["properties"]) == set(spec.arguments)
    assert schema["required"] == ["data_source_id", "spec"]


def test_registry_maps_database_and_model_names() -> None:
    registry = ToolRegistry(session_factory=None)  # type: ignore[arg-type]
    assert registry.spec_for_model_name("query_dataset").name == "builtin.query_dataset"
    assert registry.model_name_for("builtin.query_dataset") == "query_dataset"
    assert registry.spec_for_model_name("nope") is None


def test_select_grant_prefers_task_scope() -> None:
    task_id, conversation_id = uuid.uuid4(), uuid.uuid4()
    global_grant = _grant("global", None)
    conversation_grant = _grant("conversation", conversation_id)
    task_grant = _grant("task", task_id)

    winner = select_grant(
        [global_grant, conversation_grant, task_grant],
        task_id=task_id,
        conversation_id=conversation_id,
    )
    assert winner is task_grant


def test_select_grant_ignores_other_scopes() -> None:
    conversation_id = uuid.uuid4()
    other = _grant("conversation", uuid.uuid4())
    assert (
        select_grant([other], task_id=None, conversation_id=conversation_id) is None
    )


def test_select_grant_falls_back_to_global() -> None:
    global_grant = _grant("global", None)
    winner = select_grant([global_grant], task_id=uuid.uuid4(), conversation_id=uuid.uuid4())
    assert winner is global_grant


def test_select_grant_returns_none_without_candidates() -> None:
    assert select_grant([], task_id=None, conversation_id=None) is None


def test_tool_result_truncates_oversized_payload() -> None:
    huge = {"rows": ["x" * 1000 for _ in range(400)]}
    result = ToolResult(ok=True, summary="big", data=huge)
    assert result.truncated is True
    assert result.data == {"truncated": True, "reason": "result exceeded 200KB limit"}
    assert result.warnings


def test_tool_result_keeps_small_payload() -> None:
    result = ToolResult(ok=True, summary="ok", data={"rows": [1, 2, 3]})
    assert result.truncated is False
    assert result.data == {"rows": [1, 2, 3]}


def test_tool_result_failure_helper() -> None:
    result = ToolResult.failure("not_found", "missing")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "not_found"
