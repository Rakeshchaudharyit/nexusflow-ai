from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.agents import RunStatus
from app.models.approvals import ApprovalStatus, ExecutionStatus
from app.policies.engine import RiskLevel


class ReviewRequest(BaseModel):
    """Only a comment: reviewers decide on the persisted payload and cannot edit it."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    comment: str | None = Field(default=None, max_length=1000)


class ExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    team_run_id: UUID
    approval_request_id: UUID | None
    action_type: str
    payload: dict[str, Any]
    status: ExecutionStatus
    result: dict[str, Any]
    executed_by_user_id: UUID
    created_at: datetime


class ApprovalResponse(BaseModel):
    id: UUID
    organization_id: UUID
    team_run_id: UUID
    team_id: UUID
    team_name: str | None
    objective: str | None
    proposed_by_agent_id: UUID
    agent_name: str | None
    action_type: str
    payload: dict[str, Any]
    risk_level: RiskLevel
    rule_key: str
    reason: str
    status: ApprovalStatus
    requested_by_user_id: UUID
    reviewed_by_user_id: UUID | None
    review_comment: str | None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    expires_at: datetime
    execution: ExecutionResponse | None
    # M7: after approval the action runs in the worker; the run is queued until it does.
    team_run_status: RunStatus | None = None
