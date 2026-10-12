import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.identity import Timestamps

# JSONB on PostgreSQL; plain JSON keeps the SQLite test fallback working.
JSONDocument = JSON().with_variant(JSONB(), "postgresql")


def string_enum(enum: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum,
        values_callable=lambda members: [member.value for member in members],
        native_enum=False,
        create_constraint=True,
        name=name,
    )


class AgentStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class RunStatus(StrEnum):
    AWAITING_APPROVAL = "awaiting_approval"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunEventType(StrEnum):
    ACTION_PROPOSED = "action_proposed"
    POLICY_ALLOWED = "policy_allowed"
    POLICY_DENIED = "policy_denied"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_APPROVED = "approval_approved"
    APPROVAL_REJECTED = "approval_rejected"
    APPROVAL_EXPIRED = "approval_expired"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    RUN_STARTED = "run_started"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    # Team runs (M5)
    TEAM_RUN_STARTED = "team_run_started"
    SUPERVISOR_PLAN_CREATED = "supervisor_plan_created"
    HANDOFF_STARTED = "handoff_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    VALIDATION_FAILED = "validation_failed"
    REVISION_REQUESTED = "revision_requested"
    TEAM_RUN_COMPLETED = "team_run_completed"
    TEAM_RUN_FAILED = "team_run_failed"
    # Background execution (M7)
    RETRY_SCHEDULED = "retry_scheduled"
    RUN_CANCELLED = "run_cancelled"
    TEAM_RUN_CANCELLED = "team_run_cancelled"
    # Agent memory (M8): only writes are recorded; reads never create events.
    MEMORY_SAVED = "memory_saved"
    MEMORY_UPDATED = "memory_updated"


class RunEventStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class Agent(Timestamps, Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_agents_organization_slug"),
        # Target for composite foreign keys that pin runs to their agent's organization.
        UniqueConstraint("id", "organization_id", name="uq_agents_id_organization"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    instructions: Mapped[str] = mapped_column(Text)
    status: Mapped[AgentStatus] = mapped_column(
        string_enum(AgentStatus, "agent_status"),
        default=AgentStatus.DRAFT,
        server_default=AgentStatus.DRAFT.value,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    # M8: workspace memory is injected into this agent's runs only when explicitly enabled.
    workspace_memory_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )


class AgentRun(Timestamps, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_agent_runs_agent_organization",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", name="uq_agent_runs_id_organization"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_agent_runs_duration"),
        CheckConstraint("step_count >= 0", name="ck_agent_runs_step_count"),
        ForeignKeyConstraint(
            ["thread_id", "organization_id"],
            ["memory_threads.id", "memory_threads.organization_id"],
            name="fk_agent_runs_thread_organization",
        ),
        ForeignKeyConstraint(
            ["evaluation_run_id", "organization_id"],
            ["evaluation_runs.id", "evaluation_runs.organization_id"],
            name="fk_agent_runs_evaluation_run_organization",
            ondelete="CASCADE",
        ),
        Index("ix_agent_runs_thread", "thread_id"),
        Index("ix_agent_runs_organization_created", "organization_id", "created_at"),
        Index("ix_agent_runs_agent_id", "agent_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    status: Mapped[RunStatus] = mapped_column(
        string_enum(RunStatus, "agent_run_status"),
        default=RunStatus.QUEUED,
        server_default=RunStatus.QUEUED.value,
    )
    input_text: Mapped[str] = mapped_column(Text)
    final_output: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    state_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    step_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # M8: optional thread, and a count-only record of the memory injected (never the text).
    thread_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    memory_context: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    # M10: set when the run was executed by an evaluation (kept out of default run lists).
    evaluation_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class AgentRunEvent(Base):
    """Append-only execution record. Rows are inserted once and never updated.

    Each event belongs to exactly one single-agent run or one team run.
    """

    __tablename__ = "agent_run_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "organization_id"],
            ["agent_runs.id", "agent_runs.organization_id"],
            name="fk_agent_run_events_run_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["team_run_id", "organization_id"],
            ["agent_team_runs.id", "agent_team_runs.organization_id"],
            name="fk_agent_run_events_team_run_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_agent_run_events_agent_organization",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(run_id IS NULL) <> (team_run_id IS NULL)", name="ck_agent_run_events_single_parent"
        ),
        UniqueConstraint("run_id", "sequence", name="uq_agent_run_events_run_sequence"),
        UniqueConstraint("team_run_id", "sequence", name="uq_agent_run_events_team_run_sequence"),
        CheckConstraint("sequence > 0", name="ck_agent_run_events_sequence"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_agent_run_events_duration"
        ),
        CheckConstraint("attempt IS NULL OR attempt > 0", name="ck_agent_run_events_attempt"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    team_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[RunEventType] = mapped_column(
        string_enum(RunEventType, "agent_run_event_type")
    )
    node_name: Mapped[str | None] = mapped_column(String(80))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    agent_role: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[RunEventStatus] = mapped_column(
        string_enum(RunEventStatus, "agent_run_event_status")
    )
    input_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    error_message: Mapped[str | None] = mapped_column(String(500))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # Execution attempt that wrote the event (M7); NULL for events recorded outside a job.
    attempt: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
