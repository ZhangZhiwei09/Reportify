"""Memory API models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MemoryScope = Literal["global", "conversation"]
MemoryKind = Literal["preference", "fact", "definition"]


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    scope: MemoryScope = "global"
    conversation_id: UUID | None = None
    kind: MemoryKind = "fact"
    tags: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _scope_has_the_right_id(self) -> MemoryCreate:
        if self.scope == "conversation" and self.conversation_id is None:
            raise ValueError("conversation_id is required for conversation scope")
        if self.scope == "global" and self.conversation_id is not None:
            raise ValueError("conversation_id is only valid for conversation scope")
        return self


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    scope: str
    scope_id: UUID | None
    kind: str
    content: str
    tags: list[str] = Field(default_factory=list)
    created_by: str
    last_used_at: datetime | None = None
    created_at: datetime


class MemoryItem(BaseModel):
    """What the context assembler injects: id for traceability, text for reuse."""

    id: UUID
    kind: str
    content: str
