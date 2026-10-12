import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.agents import string_enum
from app.models.identity import Timestamps


class ThreadStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class MemoryType(StrEnum):
    THREAD = "thread_memory"  # notes and results that belong to one thread
    AGENT = "agent_memory"  # reusable by one agent within the organization
    WORKSPACE = "workspace_memory"  # shared across agents, only when they opt in
    FACT = "fact_memory"  # structured key/value fact at any scope
    SUMMARY = "summary_memory"  # deterministic rolling summary of one thread


class MemoryScope(StrEnum):
    THREAD = "thread"
    AGENT = "agent"
    WORKSPACE = "workspace"


class MemorySource(StrEnum):
    MANUAL = "manual_user_entry"
    USER_INPUT = "user_input"
    AGENT_RUN = "agent_run"
    TEAM_RUN = "team_run"
    APPROVED_ACTION = "approved_action"
    THREAD_SUMMARY = "thread_summary"


class MemoryThread(Timestamps, Base):
    """Groups agent runs, team runs and memory for one line of work in one organization."""

    __tablename__ = "memory_threads"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_memory_threads_id_organization"),
        Index("ix_memory_threads_organization_activity", "organization_id", "last_activity_at"),
        ForeignKeyConstraint(
            ["evaluation_run_id", "organization_id"],
            ["evaluation_runs.id", "evaluation_runs.organization_id"],
            name="fk_memory_threads_evaluation_run_organization",
            ondelete="CASCADE",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[ThreadStatus] = mapped_column(
        string_enum(ThreadStatus, "memory_thread_status"),
        default=ThreadStatus.ACTIVE,
        server_default=ThreadStatus.ACTIVE.value,
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # M10: an isolated thread owned by one evaluation run; hidden from user thread lists, so
    # evaluations never read or write user memory.
    evaluation_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class MemoryEntry(Timestamps, Base):
    """One typed, scoped, attributed memory. Never global: every row belongs to one tenant, and
    composite foreign keys pin its thread, agent and team to that same tenant."""

    __tablename__ = "memory_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["thread_id", "organization_id"],
            ["memory_threads.id", "memory_threads.organization_id"],
            name="fk_memory_entries_thread_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_memory_entries_agent_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["agent_teams.id", "agent_teams.organization_id"],
            name="fk_memory_entries_team_organization",
            ondelete="CASCADE",
        ),
        # Scope decides which column identifies the owner; nothing is ever cross-scope.
        CheckConstraint(
            "(scope = 'thread' AND thread_id IS NOT NULL)"
            " OR (scope = 'agent' AND agent_id IS NOT NULL AND thread_id IS NULL)"
            " OR (scope = 'workspace' AND thread_id IS NULL AND agent_id IS NULL)",
            name="ck_memory_entries_scope",
        ),
        CheckConstraint(
            "(memory_type IN ('thread_memory', 'summary_memory') AND scope = 'thread')"
            " OR (memory_type = 'agent_memory' AND scope = 'agent')"
            " OR (memory_type = 'workspace_memory' AND scope = 'workspace')"
            " OR (memory_type = 'fact_memory' AND fact_key IS NOT NULL"
            " AND fact_value IS NOT NULL)",
            name="ck_memory_entries_type",
        ),
        CheckConstraint("importance BETWEEN 1 AND 5", name="ck_memory_entries_importance"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_memory_entries_confidence",
        ),
        # Retry-safe writes: the writer derives one key per logical memory and upserts by it.
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_memory_entries_idempotency"
        ),
        Index("ix_memory_entries_org_thread", "organization_id", "thread_id", "is_active"),
        Index("ix_memory_entries_org_agent", "organization_id", "agent_id", "is_active"),
        Index("ix_memory_entries_org_type", "organization_id", "memory_type", "is_active"),
        Index("ix_memory_entries_source", "source_type", "source_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    memory_type: Mapped[MemoryType] = mapped_column(string_enum(MemoryType, "memory_type"))
    scope: Mapped[MemoryScope] = mapped_column(string_enum(MemoryScope, "memory_scope"))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    fact_key: Mapped[str | None] = mapped_column(String(80))
    fact_value: Mapped[str | None] = mapped_column(String(500))
    confidence: Mapped[float | None] = mapped_column(Float)
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(String(500))
    importance: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source_type: Mapped[MemorySource] = mapped_column(
        string_enum(MemorySource, "memory_source_type")
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
