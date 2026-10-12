from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.agents import RunStatus
from app.models.memory import MemoryScope, MemorySource, MemoryType, ThreadStatus


class ThreadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)


class ThreadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: ThreadStatus | None = None

    @model_validator(mode="after")
    def at_least_one(self):
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise ValueError("Provide title and/or status")
        return self


class ThreadResponse(BaseModel):
    id: UUID
    organization_id: UUID
    created_by_user_id: UUID
    title: str
    status: ThreadStatus
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    agent_run_count: int
    team_run_count: int
    memory_count: int


class ThreadRun(BaseModel):
    kind: Literal["agent", "team"]
    id: UUID
    status: RunStatus
    label: str
    created_at: datetime


class ThreadFact(BaseModel):
    id: UUID
    key: str
    value: str
    confidence: float | None
    source_type: MemorySource
    updated_at: datetime


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    memory_type: MemoryType
    scope: MemoryScope
    thread_id: UUID | None
    agent_id: UUID | None
    team_id: UUID | None
    fact_key: str | None
    fact_value: str | None
    confidence: float | None
    content: str
    summary: str | None
    importance: int
    pinned: bool
    source_type: MemorySource
    source_id: UUID | None
    created_by_user_id: UUID | None
    expires_at: datetime | None
    is_active: bool
    deactivated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Derived: active and not expired, i.e. eligible for injection into new runs.
    in_context: bool = False
    thread_title: str | None = None
    agent_name: str | None = None


class ThreadDetail(ThreadResponse):
    summary: str | None
    facts: list[ThreadFact]
    memory: list[MemoryResponse]
    recent_runs: list[ThreadRun]


FACT_KEY = r"^[a-z][a-z0-9_]{0,79}$"


class MemoryCreate(BaseModel):
    """Manual memory. Facts carry fact_key/fact_value; notes carry content."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    scope: MemoryScope
    thread_id: UUID | None = None
    agent_id: UUID | None = None
    fact_key: str | None = Field(default=None, pattern=FACT_KEY)
    fact_value: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    importance: int = Field(default=3, ge=1, le=5)
    pinned: bool = False
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def shape(self):
        if (self.fact_key is None) != (self.fact_value is None):
            raise ValueError("fact_key and fact_value go together")
        if self.fact_key is None and self.content is None:
            raise ValueError("Provide content, or fact_key and fact_value")
        owner = {
            MemoryScope.THREAD: self.thread_id is not None and self.agent_id is None,
            MemoryScope.AGENT: self.agent_id is not None and self.thread_id is None,
            MemoryScope.WORKSPACE: self.thread_id is None and self.agent_id is None,
        }
        if not owner[self.scope]:
            raise ValueError(
                "thread scope needs thread_id, agent scope needs agent_id, workspace needs neither"
            )
        return self


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str | None = Field(default=None, min_length=1, max_length=2000)
    fact_value: str | None = Field(default=None, min_length=1, max_length=500)
    importance: int | None = Field(default=None, ge=1, le=5)
    pinned: bool | None = None
    expires_at: datetime | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def at_least_one(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self


class MemoryDeleted(BaseModel):
    id: UUID
    # "deleted" for manual entries; "deactivated" for run-derived entries, kept for provenance.
    outcome: Literal["deleted", "deactivated"]
