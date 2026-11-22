"""Typed views of workspace files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class SkillMeta(BaseModel):
    name: str
    display_name: str
    description: str
    version: int = 1
    applies_to: list[str] = Field(default_factory=list)
    path: str
    content_hash: str


class TemplateMeta(BaseModel):
    name: str
    display_name: str
    description: str
    schema_version: int = 1
    path: str
    content_hash: str
    sections: list[str] = Field(default_factory=list)


class WorkspaceSnapshot(BaseModel):
    root: Path
    soul: str | None = None
    user: str | None = None
    agents: str | None = None
    skills: list[SkillMeta] = Field(default_factory=list)
    templates: list[TemplateMeta] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    loaded_at: datetime
