"""Scheduler API models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreate(BaseModel):
    task_id: UUID
    cron: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    name: str | None = Field(default=None, max_length=200)
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    cron: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    conversation_id: UUID
    name: str
    cron: str
    timezone: str
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None = None
    last_run_id: UUID | None = None
    last_status: str | None = None
    last_error: dict[str, Any] | None = None
    run_count: int = 0
