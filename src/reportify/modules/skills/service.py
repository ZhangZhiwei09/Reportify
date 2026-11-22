"""Skill index and validation (06 §Skills).

Files are the source of truth: every call re-reads the workspace, which is how
"config change takes effect without restart" (09 §12 M4) is verified.
"""

from __future__ import annotations

import re

from reportify.core.errors import InvalidArgument, NotFound
from reportify.modules.skills.schemas import (
    SkillDetail,
    SkillSummary,
    ValidationResult,
)
from reportify.modules.workspace.loader import WorkspaceLoader, WorkspaceValidationError

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class SkillService:
    def __init__(self, loader: WorkspaceLoader) -> None:
        self._loader = loader

    def _check_name(self, name: str) -> None:
        if not NAME_PATTERN.match(name or ""):
            raise InvalidArgument(f"invalid skill name: {name!r}")

    async def list(self) -> list[SkillSummary]:
        skills, _warnings = self._loader.load_skills()
        return [SkillSummary(**skill.model_dump()) for skill in skills]

    async def get(self, name: str) -> SkillDetail:
        self._check_name(name)
        skills, _warnings = self._loader.load_skills()
        meta = next((skill for skill in skills if skill.name == name), None)
        if meta is None:
            raise NotFound(f"skill not found: {name}")
        try:
            content = self._loader.read_skill(name, skills)
        except WorkspaceValidationError as exc:
            raise NotFound(str(exc)) from exc
        return SkillDetail(**meta.model_dump(), content=content)

    async def validate(self, name: str) -> ValidationResult:
        self._check_name(name)
        skills, warnings = self._loader.load_skills()
        relevant = [warning for warning in warnings if name in warning]
        if any(skill.name == name for skill in skills):
            return ValidationResult(ok=True, name=name, warnings=relevant)
        errors = relevant or [f"skill {name!r} is not loadable"]
        return ValidationResult(ok=False, name=name, errors=errors)

    async def reload(self) -> int:
        skills, _warnings = self._loader.load_skills()
        return len(skills)
