from __future__ import annotations

from pathlib import Path

import pytest

from reportify.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "REPORTIFY_DATABASE_URL",
        "postgresql+asyncpg://reportify:reportify@127.0.0.1:5432/reportify",
    )
    monkeypatch.setenv("REPORTIFY_SECRET_KEY", "test-secret")
    monkeypatch.setenv("REPORTIFY_WORKSPACE_DIR", "examples/workspace")
    monkeypatch.setenv("REPORTIFY_REPORTS_DIR", "reports")
    monkeypatch.setenv("REPORTIFY_LOG_LEVEL", "INFO")


@pytest.fixture
def settings(settings_env: None) -> Settings:
    return Settings(_env_file=None)


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()

    (root / "SOUL.md").write_text("# SOUL\n\n专业分析师。\n", encoding="utf-8")
    (root / "USER.md").write_text("# USER\n\n默认中文。\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# AGENTS\n\n必须使用工具。\n", encoding="utf-8")

    skill_dir = root / "skills" / "example"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: example\n"
        "display_name: 示例\n"
        "description: 示例分析\n"
        "version: 1\n"
        "applies_to: [示例]\n"
        "---\n\n"
        "## 步骤\n\n1. 取数\n",
        encoding="utf-8",
    )

    templates_dir = root / "report-templates"
    templates_dir.mkdir()
    (templates_dir / "default.yaml").write_text(
        "schema_version: 1\n"
        "name: default\n"
        "display_name: 默认\n"
        "description: 最小模板\n"
        "sections:\n"
        "  - id: overview\n"
        "    title: 概览\n"
        "    blocks: [kpi]\n",
        encoding="utf-8",
    )
    return root
