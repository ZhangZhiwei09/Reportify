"""Report generation service (self-contained ECharts report)."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reportify.core.errors import Conflict, NotFound, ValidationFailed
from reportify.db.models import AnalysisTask, DatasetSnapshot, ReportRef
from reportify.db.repositories import reports as reports_repo
from reportify.modules.reports import renderer as renderer_mod
from reportify.modules.reports.diff import diff_schemas
from reportify.modules.reports.schemas import (
    ReportDiff,
    ReportRefView,
    ReportRevisionRead,
    ReportSchema,
)

MAX_CHAIN = 100


class ReportService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        reports_dir: Path,
    ) -> None:
        self._session_factory = session_factory
        self._reports_dir = Path(reports_dir)

    @property
    def reports_dir(self) -> Path:
        return self._reports_dir

    async def generate(
        self,
        *,
        run_id: UUID,
        task_id: UUID,
        schema: ReportSchema,
    ) -> ReportRefView:
        refs = schema.lineage_refs()
        snapshots = await self._load_snapshots(refs)
        missing = sorted({str(ref) for ref in refs} - {str(s.id) for s in snapshots})
        if missing:
            raise ValidationFailed(
                "report references unknown dataset snapshots: " + ", ".join(missing)
            )

        report_id = uuid4()
        generated_at = datetime.now(UTC)
        lineage = self._build_lineage(schema, snapshots, generated_at)
        html = renderer_mod.render_report(
            report_id=str(report_id),
            title=schema.title,
            summary=schema.summary,
            sections=[section.model_dump(mode="json") for section in schema.sections],
            lineage=lineage,
            generated_at=generated_at,
            template_name=schema.template_name,
        )
        payload = html.encode("utf-8")
        path = self._write(report_id, payload)

        async with self._session_factory() as session:
            parent = await reports_repo.latest_for_task(session, task_id)
            version = 1 if parent is None else parent.version + 1
            report = await reports_repo.create_report(
                session,
                report_id=report_id,
                task_id=task_id,
                run_id=run_id,
                title=schema.title,
                storage_path=path.name,
                content_hash=hashlib.sha256(payload).hexdigest(),
                lineage=lineage,
                schema=schema.model_dump(mode="json"),
                version=version,
                parent_report_id=parent.id if parent is not None else None,
            )
            task = await session.get(AnalysisTask, task_id)
            if task is not None:
                task.report_ref_id = report.id
                await session.commit()

        return ReportRefView(
            **{
                "id": report.id,
                "task_id": report.task_id,
                "run_id": report.run_id,
                "title": report.title,
                "format": report.format,
                "storage_path": report.storage_path,
                "content_hash": report.content_hash,
                "status": report.status,
                "created_at": report.created_at,
                "lineage": report.lineage,
                "renderer": renderer_mod.RENDERER_ID,
                "version": report.version,
                "parent_report_id": report.parent_report_id,
            }
        )

    async def revisions(self, report_id: UUID) -> list[ReportRevisionRead]:
        """Walk ``parent_report_id`` up to the root; oldest version first."""
        async with self._session_factory() as session:
            report = await reports_repo.get_report(session, report_id)
            if report is None:
                raise NotFound(f"report not found: {report_id}")
            chain = []
            cursor = report
            seen: set[UUID] = set()
            while cursor is not None and len(chain) < MAX_CHAIN:
                if cursor.id in seen:
                    break
                seen.add(cursor.id)
                chain.append(cursor)
                if cursor.parent_report_id is None:
                    break
                cursor = await reports_repo.get_report(session, cursor.parent_report_id)
        chain.reverse()
        return [
            ReportRevisionRead(
                id=item.id,
                version=item.version,
                title=item.title,
                run_id=item.run_id,
                content_hash=item.content_hash,
                created_at=item.created_at,
            )
            for item in chain
        ]

    async def diff(self, report_id: UUID, *, against: UUID | None = None) -> ReportDiff:
        """Structured schema diff against the parent (or an explicit revision)."""
        async with self._session_factory() as session:
            target = await reports_repo.get_report(session, report_id)
            if target is None:
                raise NotFound(f"report not found: {report_id}")
            base_id = against if against is not None else target.parent_report_id
            if base_id is None:
                raise Conflict("report has no previous revision to compare")
            base = await reports_repo.get_report(session, base_id)
            if base is None:
                raise NotFound(f"report not found: {base_id}")
            if base.schema is None or target.schema is None:
                raise Conflict(
                    "stored report schema is missing; this revision cannot be diffed"
                )
            return diff_schemas(
                base.schema,
                target.schema,
                base_version=base.version,
                target_version=target.version,
            )

    async def get(self, report_id: UUID) -> ReportRef:
        async with self._session_factory() as session:
            report = await reports_repo.get_report(session, report_id)
            if report is None:
                raise NotFound(f"report not found: {report_id}")
            return report

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[ReportRef]:
        async with self._session_factory() as session:
            return list(await reports_repo.list_reports(session, limit=limit, offset=offset))

    def file_path(self, report: ReportRef) -> Path:
        """Resolve a stored path, refusing anything outside ``reports_dir``."""
        name = report.storage_path
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise NotFound("report path is not a plain file name")
        root = self._reports_dir.resolve()
        candidate = (root / name).resolve()
        if candidate.parent != root:
            raise NotFound("report path escapes reports directory")
        if not candidate.is_file():
            raise NotFound(f"report file is missing: {name}")
        return candidate

    async def _load_snapshots(self, refs: list[UUID]) -> list[DatasetSnapshot]:
        if not refs:
            return []
        async with self._session_factory() as session:
            rows = await session.execute(
                select(DatasetSnapshot).where(DatasetSnapshot.id.in_(refs))
            )
            return list(rows.scalars().all())

    def _build_lineage(
        self,
        schema: ReportSchema,
        snapshots: list[DatasetSnapshot],
        generated_at: datetime,
    ) -> dict[str, Any]:
        ordered = sorted(snapshots, key=lambda item: str(item.id))
        return {
            "generated_at": generated_at.isoformat(),
            "renderer": renderer_mod.RENDERER_ID,
            "template_name": schema.template_name,
            "snapshot_ids": [str(item.id) for item in ordered],
            "data_source_ids": sorted({str(item.data_source_id) for item in ordered}),
            "snapshots": [
                {
                    "id": str(item.id),
                    "data_source_id": str(item.data_source_id),
                    "purpose": item.purpose,
                    "sql": item.sql,
                    "params": item.params,
                    "row_count": item.row_count,
                    "filters": item.filters,
                    "executed_at": item.created_at.isoformat(),
                }
                for item in ordered
            ],
        }

    def _write(self, report_id: UUID, payload: bytes) -> Path:
        root = self._reports_dir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{report_id}.html"
        tmp = target.with_suffix(".html.tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, target)
        return target
