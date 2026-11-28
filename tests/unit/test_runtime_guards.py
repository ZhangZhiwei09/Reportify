from __future__ import annotations

from reportify.modules.runtime.runtime import hide_approval_gated
from reportify.modules.tools.schemas import ToolSpec


def _spec(
    name: str,
    *,
    risk: str = "read",
    requires_approval: bool = False,
) -> ToolSpec:
    return ToolSpec(
        name=f"builtin.{name}",
        model_name=name,
        kind="builtin_data",
        risk_level=risk,  # type: ignore[arg-type]
        requires_approval=requires_approval,
        display_name=name,
        description="test",
    )


def test_unattended_run_hides_approval_gated_tools() -> None:
    readable = _spec("query_dataset", risk="write")
    gated = _spec("fake_write", requires_approval=True)
    destructive = _spec("drop_everything", risk="destructive")

    visible, hidden = hide_approval_gated([readable, gated, destructive])

    assert [spec.model_name for spec in visible] == ["query_dataset"]
    assert hidden == ["fake_write", "drop_everything"]


def test_nothing_hidden_keeps_the_original_list() -> None:
    specs = [_spec("inspect_dataset")]

    visible, hidden = hide_approval_gated(specs)

    assert visible is specs
    assert hidden == []
