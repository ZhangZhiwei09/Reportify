"""Skills API (07 §5.4)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from reportify.api.deps import get_skill_service, require_auth
from reportify.modules.skills.schemas import SkillDetail, SkillSummary, ValidationResult
from reportify.modules.skills.service import SkillService

router = APIRouter(prefix="/api/v1/skills", tags=["skills"], dependencies=[Depends(require_auth)])


@router.get("", response_model=list[SkillSummary])
async def list_skills(
    service: Annotated[SkillService, Depends(get_skill_service)],
) -> list[SkillSummary]:
    return await service.list()


@router.post("/reload")
async def reload_skills(
    service: Annotated[SkillService, Depends(get_skill_service)],
) -> dict[str, int]:
    return {"skills": await service.reload()}


@router.get("/{name}", response_model=SkillDetail)
async def get_skill(
    name: str,
    service: Annotated[SkillService, Depends(get_skill_service)],
) -> SkillDetail:
    return await service.get(name)


@router.post("/{name}/validate", response_model=ValidationResult)
async def validate_skill(
    name: str,
    service: Annotated[SkillService, Depends(get_skill_service)],
) -> ValidationResult:
    return await service.validate(name)
