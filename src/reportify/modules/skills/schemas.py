"""Skills API models (06 §Skills)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillSummary(BaseModel):
    name: str
    display_name: str
    description: str
    version: int
    applies_to: list[str] = Field(default_factory=list)
    path: str
    content_hash: str


class SkillDetail(SkillSummary):
    content: str


class ValidationResult(BaseModel):
    ok: bool
    name: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
