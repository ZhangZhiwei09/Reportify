"""Report template index and validation (06 §Report Template).

A template only describes structure and display rules; it never contains analysis
logic. Validation is intentionally strict so a broken template cannot reach a run.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from reportify.core.config import Settings
from reportify.core.errors import InvalidArgument, NotFound, ValidationFailed
from reportify.modules.workspace.loader import WorkspaceLoader, WorkspaceValidationError

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ALLOWED_BLOCKS = frozenset({"kpi", "table", "chart", "text"})


def _invalid(reason: str) -> ValidationFailed:
    return ValidationFailed(reason)


class ReportTemplateService:
    def __init__(self, loader: WorkspaceLoader) -> None:
        self._loader = loader

    def _check_name(self, name: str) -> None:
        if not NAME_PATTERN.match(name or ""):
            raise InvalidArgument(f"invalid template name: {name!r}")

    async def list(self) -> list[dict[str, Any]]:
        templates, _warnings = self._loader.load_templates()
        return [template.model_dump() for template in templates]

    async def get(self, name: str) -> dict[str, Any]:
        self._check_name(name)
        templates, _warnings = self._loader.load_templates()
        meta = next((item for item in templates if item.name == name), None)
        if meta is None:
            raise NotFound(f"template not found: {name}")
        try:
            raw = self._loader.read_template(name, templates)
        except WorkspaceValidationError as exc:
            raise NotFound(str(exc)) from exc
        return {**meta.model_dump(), "raw": raw}

    async def validate(self, name: str) -> dict[str, Any]:
        self._check_name(name)
        templates, warnings = self._loader.load_templates()
        relevant = [warning for warning in warnings if name in warning]
        meta = next((item for item in templates if item.name == name), None)
        if meta is None:
            if relevant:
                raise _invalid("; ".join(relevant))
            raise NotFound(f"template not found: {name}")

        raw = self._loader.read_template(name, templates)
        problems = self._problems(raw)
        if problems:
            raise _invalid("; ".join(problems))
        return {
            "ok": True,
            "name": name,
            "sections": meta.sections,
            "warnings": relevant,
        }

    def _problems(self, raw: str) -> list[str]:
        try:
            data = yaml.safe_load(raw) or {}
        except yaml.YAMLError as exc:
            return [f"invalid YAML: {exc}"]
        if not isinstance(data, dict):
            return ["template must be a mapping"]

        problems: list[str] = []
        if not NAME_PATTERN.match(str(data.get("name", ""))):
            problems.append("template name must match [a-z0-9][a-z0-9-]*")

        sections = data.get("sections")
        if not isinstance(sections, list) or not sections:
            problems.append("sections must be a non-empty list")
            return problems

        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                problems.append(f"section[{index}] must be a mapping")
                continue
            for required in ("id", "title"):
                if not str(section.get(required, "")).strip():
                    problems.append(f"section[{index}] is missing {required}")
            blocks = section.get("blocks")
            if blocks is None:
                problems.append(f"section[{index}] is missing blocks")
                continue
            if not isinstance(blocks, list) or not blocks:
                problems.append(f"section[{index}].blocks must be a non-empty list")
                continue
            unknown = [str(block) for block in blocks if str(block) not in ALLOWED_BLOCKS]
            if unknown:
                problems.append(
                    f"section[{index}] has unknown blocks: {', '.join(unknown)}"
                )
        return problems

    async def reload(self) -> int:
        templates, _warnings = self._loader.load_templates()
        return len(templates)


def build_template_service(settings: Settings) -> ReportTemplateService:
    return ReportTemplateService(WorkspaceLoader(settings.workspace_dir))
