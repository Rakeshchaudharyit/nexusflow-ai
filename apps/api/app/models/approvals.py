import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.agents import JSONDocument, string_enum
from app.models.identity import Timestamps
from app.policies.engine import RiskLevel


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    # The team run was cancelled while the request was pending (M7).
    CANCELLED = "cancelled"


class ExecutionStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalRequest(Timestamps, Base):
    """A business action proposed by a team run and held for human review.

    Tied to its team run, team and proposing agent by composite keys, so it can only ever
    reference rows of its own organization. One request per team run.
    """

    __tablename__ = "approval_requests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["team_run_id", "organization_id"],
            ["agent_team_runs.id", "agent_team_runs.organization_id"],
            name="fk_approval_requests_team_run_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["agent_teams.id", "agent_teams.organization_id"],
            name="fk_approval_requests_team_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["proposed_by_agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_approval_requests_agent_organization",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", name="uq_approval_requests_id_organization"),
        UniqueConstraint("team_run_id", name="uq_approval_requests_team_run"),
        CheckConstraint("expires_at > created_at", name="ck_approval_requests_expiry"),
        Index(
            "ix_approval_requests_organization_status", "organization_id", "status", "created_at"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    team_run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    proposed_by_agent_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    action_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONDocument)
    risk_level: Mapped[RiskLevel] = mapped_column(string_enum(RiskLevel, "approval_risk_level"))
    rule_key: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[ApprovalStatus] = mapped_column(
        string_enum(ApprovalStatus, "approval_status"),
        default=ApprovalStatus.PENDING,
        server_default=ApprovalStatus.PENDING.value,
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    review_comment: Mapped[str | None] = mapped_column(String(1000))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActionExecution(Base):
    """The single execution of a team run's action (a local simulation in M6). Immutable."""

    __tablename__ = "action_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["team_run_id", "organization_id"],
            ["agent_team_runs.id", "agent_team_runs.organization_id"],
            name="fk_action_executions_team_run_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["approval_request_id", "organization_id"],
            ["approval_requests.id", "approval_requests.organization_id"],
            name="fk_action_executions_approval_organization",
            ondelete="CASCADE",
        ),
        # Exactly-once: a team run (and an approval) can produce at most one execution.
        UniqueConstraint("team_run_id", name="uq_action_executions_team_run"),
        UniqueConstraint("approval_request_id", name="uq_action_executions_approval"),
        Index("ix_action_executions_organization_created", "organization_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    team_run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONDocument)
    status: Mapped[ExecutionStatus] = mapped_column(
        string_enum(ExecutionStatus, "action_execution_status")
    )
    result: Mapped[dict[str, Any]] = mapped_column(JSONDocument)
    executed_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
