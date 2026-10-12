from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.evaluation import (
    CaseTarget,
    DatasetStatus,
    DatasetType,
    EvaluationRunStatus,
    ResultStatus,
)

PolicyDecisionName = Literal["allow", "require_approval", "deny", "none"]
RunStatusName = Literal["completed", "failed", "awaiting_approval", "cancelled"]


class CaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    target_kind: CaseTarget = CaseTarget.AGENT
    target_agent_id: UUID | None = None
    target_team_id: UUID | None = None
    input_text: str = Field(min_length=1, max_length=4000)
    setup_inputs: list[str] = Field(default_factory=list, max_length=5)
    setup_memory: list[str] = Field(default_factory=list, max_length=5)
    expected_status: RunStatusName | None = None
    expected_intent: str | None = Field(default=None, max_length=40)
    expected_tool_key: str | None = Field(default=None, max_length=300)
    expected_output_contains: list[str] = Field(default_factory=list, max_length=20)
    expected_output_excludes: list[str] = Field(default_factory=list, max_length=20)
    expected_values: dict[str, Any] = Field(default_factory=dict)
    expected_citation_documents: list[str] = Field(default_factory=list, max_length=10)
    expected_no_match: bool = False
    expected_policy_decision: PolicyDecisionName | None = None
    expected_action_type: str | None = Field(default=None, max_length=80)
    retrieval_k: int = Field(default=5, ge=1, le=20)
    position: int | None = Field(default=None, ge=0, le=10000)

    @model_validator(mode="after")
    def consistent(self):
        if self.target_kind == CaseTarget.AGENT and self.target_team_id:
            raise ValueError("agent cases cannot target a team")
        if self.target_kind == CaseTarget.TEAM and self.target_agent_id:
            raise ValueError("team cases cannot target an agent")
        if len(self.expected_values) > 20:
            raise ValueError("at most 20 expected values")
        return self


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    input_text: str | None = Field(default=None, min_length=1, max_length=4000)
    expected_status: RunStatusName | None = None
    expected_intent: str | None = Field(default=None, max_length=40)
    expected_tool_key: str | None = Field(default=None, max_length=300)
    expected_output_contains: list[str] | None = Field(default=None, max_length=20)
    expected_output_excludes: list[str] | None = Field(default=None, max_length=20)
    expected_values: dict[str, Any] | None = None
    expected_citation_documents: list[str] | None = Field(default=None, max_length=10)
    expected_no_match: bool | None = None
    expected_policy_decision: PolicyDecisionName | None = None
    expected_action_type: str | None = Field(default=None, max_length=80)
    retrieval_k: int | None = Field(default=None, ge=1, le=20)
    target_agent_id: UUID | None = None
    target_team_id: UUID | None = None
    position: int | None = Field(default=None, ge=0, le=10000)


class CaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dataset_id: UUID
    position: int
    name: str
    target_kind: CaseTarget
    target_agent_id: UUID | None
    target_team_id: UUID | None
    input_text: str
    setup_inputs: list[str]
    setup_memory: list[str]
    expected_status: str | None
    expected_intent: str | None
    expected_tool_key: str | None
    expected_output_contains: list[str]
    expected_output_excludes: list[str]
    expected_values: dict[str, Any]
    expected_citation_documents: list[str]
    expected_no_match: bool
    expected_policy_decision: str | None
    expected_action_type: str | None
    retrieval_k: int
    created_at: datetime
    updated_at: datetime


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    dataset_type: DatasetType = DatasetType.MIXED
    cases: list[CaseInput] = Field(default_factory=list, max_length=50)


class DatasetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    status: DatasetStatus | None = None


class DemoDatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # RAG cases run against this agent (it needs knowledge_search and the demo source).
    knowledge_agent_id: UUID | None = None
    name: str = Field(default="Demo · platform regression", min_length=1, max_length=120)


class DatasetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    description: str
    dataset_type: DatasetType
    status: DatasetStatus
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    case_count: int = 0
    run_count: int = 0
    last_run: "EvaluationRunSummary | None" = None


class EvaluationRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_agent_id: UUID | None = None
    target_team_id: UUID | None = None


class EvaluationRunUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_baseline: bool


class EvaluationRunSummary(BaseModel):
    id: UUID
    dataset_id: UUID
    dataset_name: str | None = None
    status: EvaluationRunStatus
    target_type: str
    target_agent_id: UUID | None
    target_team_id: UUID | None
    target_names: list[str] = []
    config_hash: str | None
    is_baseline: bool
    case_count: int
    passed_count: int
    failed_count: int
    error_count: int
    pass_rate: float | None
    score: float | None
    duration_ms: int | None
    retrieval_hit_rate: float | None = None
    retrieval_mrr: float | None = None
    error_code: str | None
    error_message: str | None
    created_by_user_id: UUID
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ResultResponse(BaseModel):
    id: UUID
    case_id: UUID
    case_name: str
    case_position: int
    target_kind: str
    input_text: str
    expected: dict[str, Any]
    actual_run_type: str | None
    actual_run_id: UUID | None
    trace_id: UUID | None
    status: ResultStatus
    passed: bool
    score: float
    checks: list[dict[str, Any]]
    failure_reasons: list[str]
    actual: dict[str, Any]
    duration_ms: int | None


class EvaluationRunDetail(EvaluationRunSummary):
    target_snapshot: dict[str, Any]
    results: list[ResultResponse]


class DatasetDetail(DatasetResponse):
    cases: list[CaseResponse]
    runs: list[EvaluationRunSummary]


class CaseChange(BaseModel):
    case_id: UUID
    case_name: str
    previous_status: str | None
    current_status: str | None
    previous_score: float | None
    current_score: float | None
    change: Literal["regression", "improvement", "unchanged", "new", "removed"]
    failed_checks: list[str]


class EvaluationComparison(BaseModel):
    previous: EvaluationRunSummary
    current: EvaluationRunSummary
    pass_rate_change: float | None
    score_change: float | None
    duration_change_ms: int | None
    config_changed: bool
    regressions: int
    improvements: int
    unchanged: int
    cases: list[CaseChange]


DatasetResponse.model_rebuild()
