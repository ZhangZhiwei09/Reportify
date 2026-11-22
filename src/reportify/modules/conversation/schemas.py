"""Conversation API models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ConversationStatus = Literal["active", "archived"]


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    status: ConversationStatus | None = None


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    status: str
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    content: str = Field(min_length=1)
    task_id: UUID | None = None
    skill_names: list[str] = Field(default_factory=list)
    template_name: str | None = Field(default=None, max_length=128)


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    task_id: UUID | None
    run_id: UUID | None
    sequence: int
    role: str
    message_type: str
    content: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MessagePage(BaseModel):
    items: list[MessageRead]
    next_after_sequence: int | None = None
    has_more: bool = False


class SendMessageResult(BaseModel):
    message_id: UUID
    task_id: UUID
    run_id: UUID


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    parent_task_id: UUID | None
    goal: str
    status: str
    skill_names: list[str] = Field(default_factory=list)
    template_name: str | None
    data_source_refs: list[dict[str, Any]] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)
    current_run_id: UUID | None
    report_ref_id: UUID | None
    error: dict[str, Any] | None
    created_at: datetime
    completed_at: datetime | None


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    conversation_id: UUID
    trigger: str
    status: str
    model_name: str
    limits: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None
    cancel_requested_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class TaskDetail(TaskRead):
    runs: list[RunRead] = Field(default_factory=list)
