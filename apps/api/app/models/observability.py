"""Observability (M10): one trace per agent/team run, with a tree of timed spans.

Traces are technical and observational. The immutable AgentRunEvent timeline (M3-M9) stays
the business record; spans never replace or duplicate it. Run status and timings are read
from the run row itself, which remains authoritative; a trace stores only what the run does
not: attempts, queue wait, retries and the span tree.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.agents import JSONDocument, string_enum
from app.models.identity import Timestamps


class TraceRunType(StrEnum):
    AGENT = "agent"
    TEAM = "team"


class SpanType(StrEnum):
    WORKER = "worker"  # one execution attempt on a worker (M7 job attempt)
    GRAPH_NODE = "graph_node"  # a LangGraph node of the single-agent graph
    AGENT = "agent"  # a team member's work (or the supervisor's plan)
    TOOL = "tool"  # internal tool call
    MCP = "mcp"  # MCP tool call
    KNOWLEDGE_SEARCH = "knowledge_search"  # M9 retrieval
    MEMORY_RETRIEVAL = "memory_retrieval"  # M8 context load
    POLICY = "policy"  # M6 policy evaluation (or "no action proposed")
    APPROVAL = "approval"  # approval requested / approved / rejected
    ACTION = "action"  # simulated business action execution
    RETRY = "retry"  # an attempt ended and the job was re-queued (or recovered)


class SpanStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PENDING = "pending"  # e.g. an approval that is waiting for a human
    LOST = "lost"  # the attempt lost its job (recovered elsewhere)


class RunTrace(Timestamps, Base):
    __tablename__ = "run_traces"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_run_id", "organization_id"],
            ["agent_runs.id", "agent_runs.organization_id"],
            name="fk_run_traces_agent_run_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["team_run_id", "organization_id"],
            ["agent_team_runs.id", "agent_team_runs.organization_id"],
            name="fk_run_traces_team_run_organization",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(run_type = 'agent' AND agent_run_id IS NOT NULL AND team_run_id IS NULL)"
            " OR (run_type = 'team' AND team_run_id IS NOT NULL AND agent_run_id IS NULL)",
            name="ck_run_traces_run",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_run_traces_attempts"),
        UniqueConstraint("id", "organization_id", name="uq_run_traces_id_organization"),
        # Deterministic linkage: exactly one trace per run, retries included.
        UniqueConstraint("agent_run_id", name="uq_run_traces_agent_run"),
        UniqueConstraint("team_run_id", name="uq_run_traces_team_run"),
        Index("ix_run_traces_organization_created", "organization_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    run_type: Mapped[TraceRunType] = mapped_column(string_enum(TraceRunType, "trace_run_type"))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    team_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # Informational copies for filtering (the run row is authoritative).
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    evaluation_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # First attempt: worker claim time minus job creation (real, measured at claim).
    queue_wait_ms: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    span_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error_category: Mapped[str | None] = mapped_column(String(20))


class TraceSpan(Base):
    """One timed unit of work. Insert-only; summaries and metadata are bounded and sanitized."""

    __tablename__ = "trace_spans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["trace_id", "organization_id"],
            ["run_traces.id", "run_traces.organization_id"],
            name="fk_trace_spans_trace_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["parent_span_id"],
            ["trace_spans.id"],
            name="fk_trace_spans_parent",
            ondelete="CASCADE",
        ),
        UniqueConstraint("trace_id", "sequence", name="uq_trace_spans_trace_sequence"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="ck_trace_spans_duration"),
        Index("ix_trace_spans_org_type_started", "organization_id", "span_type", "started_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    trace_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    parent_span_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    span_type: Mapped[SpanType] = mapped_column(string_enum(SpanType, "trace_span_type"))
    name: Mapped[str] = mapped_column(String(120))
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[SpanStatus] = mapped_column(string_enum(SpanStatus, "trace_span_status"))
    attempt: Mapped[int | None] = mapped_column(Integer)
    # Observational references (no FK: deleting a tool server must not erase history).
    agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    tool_key: Mapped[str | None] = mapped_column(String(300))
    mcp_server_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    knowledge_source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Fractional milliseconds from a monotonic clock (local steps often take < 1 ms).
    duration_ms: Mapped[float | None] = mapped_column(Float)
    input_summary: Mapped[str | None] = mapped_column(String(500))
    output_summary: Mapped[str | None] = mapped_column(String(500))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONDocument, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_category: Mapped[str | None] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
