from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.agents import AgentStatus, RunEventStatus, RunEventType, RunStatus
from app.models.jobs import JobStatus
from app.schemas.jobs import ExecutionInfo


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(min_length=1, max_length=4000)


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    instructions: str | None = Field(default=None, min_length=1, max_length=4000)
    status: AgentStatus | None = None
    # M8: opt this agent in to workspace-scoped memory.
    workspace_memory_enabled: bool | None = None

    @model_validator(mode="after")
    def reject_null_values(self):
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        return self


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str
    instructions: str
    status: AgentStatus
    workspace_memory_enabled: bool = False
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class AgentRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    input: str = Field(min_length=1, max_length=2000)
    # M8: run inside a memory thread (optional; runs without a thread behave as before).
    thread_id: UUID | None = None


class RunError(BaseModel):
    code: str
    message: str


class ToolCall(BaseModel):
    """One tool invocation as shown to clients; MCP calls carry their server."""

    tool_key: str
    tool_type: str
    tool: str
    status: str
    server_id: str | None = None
    server_name: str | None = None
    duration_ms: int | None = None


class AgentRunResult(BaseModel):
    """Structured result of executing a run; never raw LangGraph state."""

    run_id: UUID
    agent_id: UUID
    status: RunStatus
    intent: str | None
    summary: str | None
    tools_used: list[str]
    tool_calls: list[ToolCall]
    duration_ms: int | None
    step_count: int
    error: RunError | None
    created_at: datetime | None = None
    # M7: the background job executing this run.
    execution: ExecutionInfo | None = None
    thread_id: UUID | None = None


class AgentRunSummary(BaseModel):
    id: UUID
    agent_id: UUID
    created_by_user_id: UUID | None = None
    agent_name: str
    status: RunStatus
    input_text: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    step_count: int
    # M7: status of the run's latest job, e.g. "retrying" while a retry is scheduled.
    execution_status: JobStatus | None = None
    thread_id: UUID | None = None


class AgentRunEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence: int
    event_type: RunEventType
    node_name: str | None
    agent_id: UUID | None = None
    agent_role: str | None = None
    status: RunEventStatus
    input_payload: dict[str, Any] | None
    output_payload: dict[str, Any] | None
    error_message: str | None
    duration_ms: int | None
    attempt: int | None = None
    created_at: datetime


class AgentRunDetail(AgentRunSummary):
    final_output: dict[str, Any] | None
    state: dict[str, Any] | None
    error: RunError | None
    tool_calls: list[ToolCall]
    events: list[AgentRunEventResponse]
    execution: ExecutionInfo | None = None
    # M8: counts of the memory injected (never the memory text).
    memory_context: dict[str, Any] | None = None
    # M9: the knowledge retrieval this run performed (query, sources, ranked chunks).
    knowledge: dict[str, Any] | None = None
