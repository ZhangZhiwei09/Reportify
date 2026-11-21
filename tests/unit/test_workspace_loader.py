from __future__ import annotations

from pathlib import Path

import pytest

from reportify.modules.workspace.loader import WorkspaceLoader


def test_loads_valid_workspace(workspace_root: Path) -> None:
    snapshot = WorkspaceLoader(workspace_root).load()

    assert snapshot.warnings == []
    assert snapshot.soul is not None
    assert "专业分析师" in snapshot.soul
    assert [skill.name for skill in snapshot.skills] == ["example"]
    assert [template.name for template in snapshot.templates] == ["default"]
    assert snapshot.skills[0].content_hash


def test_missing_root_returns_warning(tmp_path: Path) -> None:
    snapshot = WorkspaceLoader(tmp_path / "missing").load()

    assert snapshot.soul is None
    assert any("workspace root not found" in warning for warning in snapshot.warnings)


def test_invalid_skill_is_skipped(workspace_root: Path) -> None:
    bad_dir = workspace_root / "skills" / "bad"
    bad_dir.mkdir()
    (bad_dir / "SKILL.md").write_text("no frontmatter", encoding="utf-8")

    snapshot = WorkspaceLoader(workspace_root).load()

    assert [skill.name for skill in snapshot.skills] == ["example"]
    assert any("skills/bad" in warning for warning in snapshot.warnings)


def test_invalid_template_is_skipped(workspace_root: Path) -> None:
    broken = workspace_root / "report-templates" / "broken.yaml"
    broken.write_text("name: [", encoding="utf-8")

    snapshot = WorkspaceLoader(workspace_root).load()

    assert [template.name for template in snapshot.templates] == ["default"]
    assert any("broken.yaml" in warning for warning in snapshot.warnings)


def test_oversized_file_is_rejected(workspace_root: Path) -> None:
    (workspace_root / "SOUL.md").write_text("x" * 200, encoding="utf-8")

    snapshot = WorkspaceLoader(workspace_root, max_file_bytes=100).load()

    assert snapshot.soul is None
    assert any("exceeds" in warning for warning in snapshot.warnings)


def test_symlink_escape_is_rejected(workspace_root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")

    link = workspace_root / "SOUL.md"
    link.unlink()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available on this platform")

    snapshot = WorkspaceLoader(workspace_root).load()

    assert snapshot.soul is None
    assert any("escapes workspace" in warning for warning in snapshot.warnings)
