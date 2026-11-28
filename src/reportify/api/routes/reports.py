"""Report metadata and download routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from reportify.api.deps import get_report_service, require_auth
from reportify.modules.reports.schemas import ReportRefView
from reportify.modules.reports.service import ReportService

router = APIRouter(
    prefix="/api/v1/reports",
    tags=["reports"],
    dependencies=[Depends(require_auth)],
)

REPORT_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "img-src data:; "
    "style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


@router.get("", response_model=list[ReportRefView])
async def list_reports(
    service: Annotated[ReportService, Depends(get_report_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReportRefView]:
    rows = await service.list(limit=limit, offset=offset)
    return [ReportRefView.model_validate(row) for row in rows]


@router.get("/{report_id}", response_model=ReportRefView)
async def get_report(
    report_id: UUID,
    service: Annotated[ReportService, Depends(get_report_service)],
) -> ReportRefView:
    report = await service.get(report_id)
    return ReportRefView.model_validate(report)


@router.get("/{report_id}/download")
async def download_report(
    report_id: UUID,
    service: Annotated[ReportService, Depends(get_report_service)],
) -> FileResponse:
    report = await service.get(report_id)
    path = service.file_path(report)
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        filename=path.name,
        headers={
            "Cache-Control": "no-store",
            # A report is a standalone artifact with inline ECharts; the console
            # keeps its strict CSP, only this file gets its own policy.
            "Content-Security-Policy": REPORT_CONTENT_SECURITY_POLICY,
            "X-Content-Type-Options": "nosniff",
        },
    )
