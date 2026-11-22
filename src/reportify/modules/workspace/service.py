"""Workspace file API and audit writing (07 §5.4, 08 §6.19).

Files remain the source of truth; this service only exposes them and records what
was loaded, changed or rejected so a bad edit is traceable.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.core.errors import NotFound, ValidationFailed
from reportify.db.repositories import workspace as workspace_repo
from reportify.modules.workspace.loader import WorkspaceLoader, WorkspaceValidationError


class WorkspaceService:
    def __init__(
        self,
        loader: WorkspaceLoader,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._loader = loader
        self._session_factory = session_factory

    def list_files(self) -> list[dict[str, Any]]:
        return self._loader.walk_files()

    def read_file(self, path: str) -> dict[str, Any]:
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValidationFailed(f"invalid workspace path: {path!r}")
        try:
            content = self._loader.read_file(path)
        except WorkspaceValidationError as exc:
            message = str(exc)
            if "escapes workspace" in message:
                raise ValidationFailed(message) from exc
            raise NotFound(message) from exc
        return {"path": path, "content": content}

    async def reload(self, *, actor: str = "api") -> dict[str, Any]:
        snapshot = self._loader.load()
        files = self._loader.walk_files()
        skills = len(snapshot.skills)
        templates = len(snapshot.templates)

        written = {"loaded": 0, "changed": 0, "rejected": 0}
        async with self._session_factory() as session:
            known = await workspace_repo.latest_hashes(session)
            for item in files:
                previous = known.get(item["path"])
                if previous is None:
                    action = "loaded"
                elif previous != item["hash"]:
                    action = "changed"
                else:
                    continue
                await workspace_repo.write_audit(
                    session,
                    file_path=item["path"],
                    content_hash=item["hash"],
                    action=action,
                    actor=actor,
                    detail={"size": item["size"]},
                )
                written[action] += 1

            for warning in snapshot.warnings:
                file_path = warning.split(":", 1)[0] if ":" in warning else "<workspace>"
                await workspace_repo.write_audit(
                    session,
                    file_path=file_path,
                    content_hash="0" * 64,
                    action="rejected",
                    actor=actor,
                    detail={"reason": warning},
                )
                written["rejected"] += 1

        return {
            "files": len(files),
            "skills": skills,
            "templates": templates,
            "warnings": snapshot.warnings,
            "audit": written,
        }

    async def audits(self, *, limit: int = 100, action: str | None = None) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            rows = await workspace_repo.list_audits(session, limit=limit, action=action)
        return [
            {
                "id": str(row.id),
                "file_path": row.file_path,
                "content_hash": row.content_hash,
                "action": row.action,
                "actor": row.actor,
                "detail": row.detail,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
