"""Evaluation (M10): deterministic expectations checked against real runs.

Separate from observability: traces record what happened; evaluations judge it against
expectations. A dataset holds cases; an evaluation run executes every case through the real
agent/team runtime (in the M7 worker) and stores one result per case.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.agents import JSONDocument, string_enum
from app.models.identity import Timestamps


class DatasetType(StrEnum):
    AGENT = "agent"
    TEAM = "team"
    RAG = "rag"
    POLICY = "policy"
    MIXED = "mixed"


class DatasetStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class CaseTarget(StrEnum):
    AGENT = "agent"
    TEAM = "team"


class EvaluationRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResultStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"  # an expectation did not hold (a completed evaluation, not an error)
    ERROR = "error"  # the case could not be executed (e.g. no target configured)


class EvaluationDataset(Timestamps, Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_evaluation_datasets_id_organization"),
        UniqueConstraint("organization_id", "name", name="uq_evaluation_datasets_org_name"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    dataset_type: Mapped[DatasetType] = mapped_column(
        string_enum(DatasetType, "evaluation_dataset_type")
    )
    status: Mapped[DatasetStatus] = mapped_column(
        string_enum(DatasetStatus, "evaluation_dataset_status"),
        default=DatasetStatus.ACTIVE,
        server_default=DatasetStatus.ACTIVE.value,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )


class EvaluationCase(Timestamps, Base):
    """One input plus deterministic expectations. Every expectation is optional; only the ones
    set become checks."""

    __tablename__ = "evaluation_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "organization_id"],
            ["evaluation_datasets.id", "evaluation_datasets.organization_id"],
            name="fk_evaluation_cases_dataset_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["target_agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_evaluation_cases_agent_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["target_team_id", "organization_id"],
            ["agent_teams.id", "agent_teams.organization_id"],
            name="fk_evaluation_cases_team_organization",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", name="uq_evaluation_cases_id_organization"),
        Index("ix_evaluation_cases_dataset_position", "dataset_id", "position"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    name: Mapped[str] = mapped_column(String(120))
    target_kind: Mapped[CaseTarget] = mapped_column(string_enum(CaseTarget, "evaluation_target"))
    # Optional per-case target; otherwise the evaluation run's agent/team is used.
    target_agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    target_team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    input_text: Mapped[str] = mapped_column(Text)
    # Inputs run first in the case's isolated evaluation thread (e.g. a lookup before recall).
    setup_inputs: Mapped[list[str]] = mapped_column(JSONDocument, default=list)
    # Manual notes written to the case's evaluation thread before the run (adversarial memory).
    setup_memory: Mapped[list[str]] = mapped_column(JSONDocument, default=list)
    expected_status: Mapped[str | None] = mapped_column(String(20))
    expected_intent: Mapped[str | None] = mapped_column(String(40))
    # A tool key, a pattern with * (mcp:*:calculate), or "none" for "no tool call".
    expected_tool_key: Mapped[str | None] = mapped_column(String(300))
    expected_output_contains: Mapped[list[str]] = mapped_column(JSONDocument, default=list)
    expected_output_excludes: Mapped[list[str]] = mapped_column(JSONDocument, default=list)
    # Dotted paths into the final output, e.g. {"validation.confidence": 0.95}.
    expected_values: Mapped[dict[str, Any]] = mapped_column(JSONDocument, default=dict)
    expected_citation_documents: Mapped[list[str]] = mapped_column(JSONDocument, default=list)
    expected_no_match: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # allow | require_approval | deny | none
    expected_policy_decision: Mapped[str | None] = mapped_column(String(20))
    expected_action_type: Mapped[str | None] = mapped_column(String(80))
    retrieval_k: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONDocument, default=dict)


class EvaluationRun(Timestamps, Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "organization_id"],
            ["evaluation_datasets.id", "evaluation_datasets.organization_id"],
            name="fk_evaluation_runs_dataset_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["target_agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_evaluation_runs_agent_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["target_team_id", "organization_id"],
            ["agent_teams.id", "agent_teams.organization_id"],
            name="fk_evaluation_runs_team_organization",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", name="uq_evaluation_runs_id_organization"),
        CheckConstraint(
            "passed_count >= 0 AND failed_count >= 0", name="ck_evaluation_runs_counts"
        ),
        Index("ix_evaluation_runs_org_dataset_status", "organization_id", "dataset_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[EvaluationRunStatus] = mapped_column(
        string_enum(EvaluationRunStatus, "evaluation_run_status"),
        default=EvaluationRunStatus.QUEUED,
        server_default=EvaluationRunStatus.QUEUED.value,
    )
    # agent | team | mixed (both an agent and a team are configured)
    target_type: Mapped[str] = mapped_column(String(10))
    target_agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    target_team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # What was evaluated: safe configuration of every target used, and its hash.
    target_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONDocument, default=dict)
    config_hash: Mapped[str | None] = mapped_column(String(64))
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    case_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    passed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Mean case score (share of checks passed), 0..1; null until completed.
    score: Mapped[float | None] = mapped_column(Float)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["evaluation_run_id", "organization_id"],
            ["evaluation_runs.id", "evaluation_runs.organization_id"],
            name="fk_evaluation_results_run_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["case_id", "organization_id"],
            ["evaluation_cases.id", "evaluation_cases.organization_id"],
            name="fk_evaluation_results_case_organization",
            ondelete="CASCADE",
        ),
        # One result per case per run: a retried evaluation job resumes, never duplicates.
        UniqueConstraint("evaluation_run_id", "case_id", name="uq_evaluation_results_run_case"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    case_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    # The real run that was evaluated (agent or team), for drill-down into its trace.
    actual_run_type: Mapped[str | None] = mapped_column(String(10))
    actual_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[ResultStatus] = mapped_column(string_enum(ResultStatus, "evaluation_result"))
    passed: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[float] = mapped_column(Float)
    checks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONDocument, default=list)
    failure_reasons: Mapped[list[str]] = mapped_column(JSONDocument, default=list)
    # Observed values for display (intent, tools, status, top documents...), bounded.
    actual_json: Mapped[dict[str, Any]] = mapped_column(JSONDocument, default=dict)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
