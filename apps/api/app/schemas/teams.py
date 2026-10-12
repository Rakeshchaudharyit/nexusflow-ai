from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.agents import AgentStatus, RunStatus
from app.models.jobs import JobStatus
from app.models.teams import TeamRole, TeamStatus
from app.schemas.agents import AgentRunEventResponse, RunError
from app.schemas.jobs import ExecutionInfo


def reject_nulls(model: BaseModel) -> BaseModel:
    for field in model.model_fields_set:
        if getattr(model, field) is None:
            raise ValueError(f"{field} cannot be null")
    if not model.model_fields_set:
        raise ValueError("Provide at least one field to update")
    return model


class TeamMemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: UUID
    role: TeamRole
    is_required: bool = True
    position: int = Field(default=0, ge=0, le=100)


class TeamMemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: TeamRole | None = None
    is_required: bool | None = None
    position: int | None = Field(default=None, ge=0, le=100)

    _check = model_validator(mode="after")(reject_nulls)


class TeamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    members: list[TeamMemberInput] = Field(default_factory=list, max_length=12)


class TeamUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    status: TeamStatus | None = None
    # M8: let the supervisor receive workspace-scoped memory.
    workspace_memory_enabled: bool | None = None

    _check = model_validator(mode="after")(reject_nulls)


class AgentToolResponse(BaseModel):
    id: UUID
    agent_id: UUID
    tool_key: str
    tool_type: str
    is_enabled: bool
    created_at: datetime


class AgentToolCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    tool_key: str = Field(min_length=3, max_length=300)


class AgentToolUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_enabled: bool


class ToolCatalogEntry(BaseModel):
    tool_key: str
    tool_type: str
    name: str
    description: str
    server_name: str | None = None
    is_enabled: bool


class MemberKnowledge(BaseModel):
    source_id: UUID
    source_name: str
    source_status: str
    is_enabled: bool


class TeamMemberResponse(BaseModel):
    id: UUID
    agent_id: UUID
    agent_name: str
    agent_status: AgentStatus
    role: TeamRole
    position: int
    is_required: bool
    tools: list[AgentToolResponse]
    # M9: knowledge sources the member's agent may search (with internal:knowledge_search).
    knowledge_sources: list[MemberKnowledge] = []


class TeamResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    slug: str
    description: str
    status: TeamStatus
    workspace_memory_enabled: bool = False
    member_count: int
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


class TeamDetail(TeamResponse):
    members: list[TeamMemberResponse]
    problems: list[str]


class TeamRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    objective: str = Field(min_length=1, max_length=2000)
    thread_id: UUID | None = None


class AgentStepResult(BaseModel):
    """What one team member contributed, derived from the run's events."""

    agent_id: UUID | None
    agent_name: str | None
    role: str
    status: str
    output: dict[str, Any] | None
    tool_calls: list[dict[str, Any]]
    duration_ms: int | None
    error: RunError | None


class Handoff(BaseModel):
    sequence: int
    to_role: str
    agent_name: str | None
    task: str
    context: dict[str, Any]


class TeamRunResult(BaseModel):
    run_id: UUID
    team_id: UUID
    status: RunStatus
    final_output: dict[str, Any] | None
    agents_executed: list[str]
    duration_ms: int | None
    step_count: int
    error: RunError | None
    # M6: the proposed business action and its policy outcome, when the objective asked for one.
    action: dict[str, Any] | None = None
    created_at: datetime | None = None
    execution: ExecutionInfo | None = None
    thread_id: UUID | None = None


class TeamRunSummary(BaseModel):
    id: UUID
    team_id: UUID
    created_by_user_id: UUID | None = None
    team_name: str
    status: RunStatus
    objective: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    step_count: int
    execution_status: JobStatus | None = None
    thread_id: UUID | None = None


class TeamRunDetail(TeamRunSummary):
    plan: list[dict[str, Any]]
    final_output: dict[str, Any] | None
    validation: dict[str, Any] | None
    revisions: int
    results: list[AgentStepResult]
    handoffs: list[Handoff]
    error: RunError | None
    action: dict[str, Any] | None = None
    approval: dict[str, Any] | None = None
    events: list[AgentRunEventResponse]
    execution: ExecutionInfo | None = None
    memory_context: dict[str, Any] | None = None
