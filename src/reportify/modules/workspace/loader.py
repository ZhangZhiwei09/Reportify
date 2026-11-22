"""Load and validate workspace files.

The loader is intentionally strict about paths and encodings: workspace files
are user-authored configuration, not trusted code, and must never read outside
the configured root.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from reportify.modules.workspace.schemas import SkillMeta, TemplateMeta, WorkspaceSnapshot

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)


class WorkspaceValidationError(ValueError):
    """A workspace file is invalid or unsafe to load."""


class WorkspaceLoader:
    def __init__(self, root: Path, *, max_file_bytes: int = 128 * 1024) -> None:
        self._root = Path(root).expanduser().resolve()
        self._max_file_bytes = max_file_bytes

    def load(self) -> WorkspaceSnapshot:
        loaded_at = datetime.now(UTC)
        if not self._root.is_dir():
            return WorkspaceSnapshot(
                root=self._root,
                warnings=[f"workspace root not found: {self._root}"],
                loaded_at=loaded_at,
            )

        warnings: list[str] = []
        return WorkspaceSnapshot(
            root=self._root,
            soul=self._read_optional("SOUL.md", warnings),
            user=self._read_optional("USER.md", warnings),
            agents=self._read_optional("AGENTS.md", warnings),
            skills=self._load_skills(warnings),
            templates=self._load_templates(warnings),
            warnings=warnings,
            loaded_at=loaded_at,
        )

    def skills_index(self) -> list[SkillMeta]:
        return self.load_skills()[0]

    def load_skills(self) -> tuple[list[SkillMeta], list[str]]:
        """Skills plus the per-skill load warnings."""
        warnings: list[str] = []
        return self._load_skills(warnings), warnings

    def load_templates(self) -> tuple[list[TemplateMeta], list[str]]:
        warnings: list[str] = []
        return self._load_templates(warnings), warnings

    def walk_files(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """List workspace files with size and content hash (root-bounded)."""
        if not self._root.is_dir():
            return []
        files: list[dict[str, Any]] = []
        for path in sorted(self._root.rglob("*")):
            if len(files) >= limit:
                break
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(self._root)
            if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                continue
            try:
                data = path.read_bytes()
            except OSError:  # pragma: no cover - unreadable file
                continue
            files.append(
                {
                    "path": relative.as_posix(),
                    "size": len(data),
                    "hash": hashlib.sha256(data).hexdigest(),
                }
            )
        return files

    def read_file(self, relative: str) -> str:
        """Read one workspace file by relative path (path traversal rejected)."""
        candidate = self._root / relative
        return self._read_text(candidate)

    def read_skill(self, name: str, skills: list[SkillMeta] | None = None) -> str:
        """Return the full ``SKILL.md`` text for one skill.

        Used by the ``load_skill`` tool for progressive disclosure: the index is
        always in context, the body only on demand (02 §6).
        """
        metas = skills if skills is not None else self.skills_index()
        meta = next((item for item in metas if item.name == name), None)
        if meta is None:
            raise WorkspaceValidationError(f"skill not found: {name}")
        return self._read_text(self._root / meta.path)

    def read_template(
        self,
        name: str,
        templates: list[TemplateMeta] | None = None,
    ) -> str:
        metas = templates if templates is not None else self.templates_index()
        meta = next((item for item in metas if item.name == name), None)
        if meta is None:
            raise WorkspaceValidationError(f"template not found: {name}")
        return self._read_text(self._root / meta.path)

    def templates_index(self) -> list[TemplateMeta]:
        warnings: list[str] = []
        return self._load_templates(warnings)

    def _read_optional(self, relative: str, warnings: list[str]) -> str | None:
        path = self._root / relative
        if not path.exists():
            return None
        try:
            return self._read_text(path)
        except WorkspaceValidationError as exc:
            warnings.append(f"{relative}: {exc}")
            return None

    def _read_text(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise WorkspaceValidationError(f"path escapes workspace: {path}") from exc

        if not resolved.is_file():
            raise WorkspaceValidationError(f"not a file: {path}")

        size = resolved.stat().st_size
        if size > self._max_file_bytes:
            raise WorkspaceValidationError(
                f"file exceeds {self._max_file_bytes} bytes: {path}"
            )

        data = resolved.read_bytes()
        if b"\x00" in data:
            raise WorkspaceValidationError(f"binary file is not allowed: {path}")

        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise WorkspaceValidationError(f"file is not valid UTF-8: {path}") from exc

    def _load_skills(self, warnings: list[str]) -> list[SkillMeta]:
        skills_dir = self._root / "skills"
        if not skills_dir.is_dir():
            return []

        skills: list[SkillMeta] = []
        for entry in sorted(skills_dir.iterdir(), key=lambda item: item.name):
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file():
                warnings.append(f"skills/{entry.name}: SKILL.md not found")
                continue
            try:
                text = self._read_text(skill_file)
                skills.append(self._parse_skill(entry.name, skill_file, text))
            except WorkspaceValidationError as exc:
                warnings.append(f"skills/{entry.name}: {exc}")
        return skills

    def _parse_skill(self, directory: str, path: Path, text: str) -> SkillMeta:
        data = _load_frontmatter(text)
        name = str(data.get("name", "")).strip()
        if name != directory:
            raise WorkspaceValidationError(
                f"skill name {name!r} does not match directory {directory!r}"
            )
        if not _NAME_RE.match(name):
            raise WorkspaceValidationError(f"invalid skill name: {name!r}")

        description = str(data.get("description", "")).strip()
        if not description:
            raise WorkspaceValidationError("skill description is required")

        try:
            version = int(data.get("version", 1))
        except (TypeError, ValueError) as exc:
            raise WorkspaceValidationError("skill version must be an integer") from exc

        applies_to = data.get("applies_to") or []
        if not isinstance(applies_to, list) or not all(
            isinstance(item, str) for item in applies_to
        ):
            raise WorkspaceValidationError("skill applies_to must be a list of strings")

        return SkillMeta(
            name=name,
            display_name=str(data.get("display_name") or name),
            description=description,
            version=version,
            applies_to=applies_to,
            path=self._relative(path),
            content_hash=_sha256(text),
        )

    def _load_templates(self, warnings: list[str]) -> list[TemplateMeta]:
        templates_dir = self._root / "report-templates"
        if not templates_dir.is_dir():
            return []

        templates: list[TemplateMeta] = []
        for path in sorted(templates_dir.iterdir(), key=lambda item: item.name):
            if path.suffix.lower() not in {".yaml", ".yml"}:
                continue
            try:
                text = self._read_text(path)
                data = yaml.safe_load(text) or {}
                templates.append(self._parse_template(path, text, data))
            except (WorkspaceValidationError, ValueError, yaml.YAMLError) as exc:
                warnings.append(f"report-templates/{path.name}: {exc}")
        return templates

    def _parse_template(self, path: Path, text: str, data: Any) -> TemplateMeta:
        if not isinstance(data, dict):
            raise WorkspaceValidationError("template must be a mapping")

        name = str(data.get("name") or path.stem).strip()
        if not _NAME_RE.match(name):
            raise WorkspaceValidationError(f"invalid template name: {name!r}")

        sections = data.get("sections")
        if not isinstance(sections, list) or not sections:
            raise WorkspaceValidationError("template sections must be a non-empty list")

        try:
            schema_version = int(data.get("schema_version", 1))
        except (TypeError, ValueError) as exc:
            raise WorkspaceValidationError("schema_version must be an integer") from exc

        return TemplateMeta(
            name=name,
            display_name=str(data.get("display_name") or name),
            description=str(data.get("description") or ""),
            schema_version=schema_version,
            path=self._relative(path),
            content_hash=_sha256(text),
            sections=[
                str(section.get("title") or section.get("id") or "")
                for section in sections
                if isinstance(section, dict)
            ],
        )

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self._root).as_posix()


def _load_frontmatter(text: str) -> dict[str, Any]:
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise WorkspaceValidationError("SKILL.md must start with YAML frontmatter")
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise WorkspaceValidationError(f"invalid frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkspaceValidationError("frontmatter must be a mapping")
    return data


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
