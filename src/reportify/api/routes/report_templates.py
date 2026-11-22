"""Report template API (07 §5.4)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from reportify.api.deps import get_template_service, require_auth
from reportify.modules.reports.templates import ReportTemplateService

router = APIRouter(
    prefix="/api/v1/report-templates",
    tags=["report-templates"],
    dependencies=[Depends(require_auth)],
)


@router.get("")
async def list_templates(
    service: Annotated[ReportTemplateService, Depends(get_template_service)],
) -> list[dict[str, Any]]:
    return await service.list()


@router.post("/reload")
async def reload_templates(
    service: Annotated[ReportTemplateService, Depends(get_template_service)],
) -> dict[str, int]:
    return {"templates": await service.reload()}


@router.get("/{name}")
async def get_template(
    name: str,
    service: Annotated[ReportTemplateService, Depends(get_template_service)],
) -> dict[str, Any]:
    return await service.get(name)


@router.post("/{name}/validate")
async def validate_template(
    name: str,
    service: Annotated[ReportTemplateService, Depends(get_template_service)],
) -> dict[str, Any]:
    return await service.validate(name)
