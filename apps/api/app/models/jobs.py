import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.agents import string_enum
from app.models.identity import Timestamps


class JobType(StrEnum):
    SINGLE_AGENT_RUN = "single_agent_run"
    TEAM_RUN = "team_run"
    APPROVAL_ACTION = "approval_action"
    # M9: extract, chunk and embed one knowledge document (also used for re-indexing).
    KNOWLEDGE_INGESTION = "knowledge_ingestion"
    # M10: execute every case of an evaluation run through the real runtimes.
    EVALUATION_RUN = "evaluation_run"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    # Waiting for next_retry_at after a retryable failure or a lost worker.
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRYING)

# Exactly the resource columns of each job type are set (M9 adds knowledge_document_id).
RESOURCE_CHECK = (
    "(job_type = 'single_agent_run' AND agent_run_id IS NOT NULL AND team_run_id IS NULL"
    " AND approval_request_id IS NULL AND knowledge_document_id IS NULL"
    " AND evaluation_run_id IS NULL)"
    " OR (job_type = 'team_run' AND team_run_id IS NOT NULL AND agent_run_id IS NULL"
    " AND approval_request_id IS NULL AND knowledge_document_id IS NULL"
    " AND evaluation_run_id IS NULL)"
    " OR (job_type = 'approval_action' AND team_run_id IS NOT NULL"
    " AND approval_request_id IS NOT NULL AND agent_run_id IS NULL"
    " AND knowledge_document_id IS NULL AND evaluation_run_id IS NULL)"
    " OR (job_type = 'knowledge_ingestion' AND knowledge_document_id IS NOT NULL"
    " AND agent_run_id IS NULL AND team_run_id IS NULL AND approval_request_id IS NULL"
    " AND evaluation_run_id IS NULL)"
    " OR (job_type = 'evaluation_run' AND evaluation_run_id IS NOT NULL"
    " AND agent_run_id IS NULL AND team_run_id IS NULL AND approval_request_id IS NULL"
    " AND knowledge_document_id IS NULL)"
)


class ExecutionJob(Timestamps, Base):
    """Durable unit of background work. PostgreSQL is authoritative; Redis only carries the id.

    Exactly one resource column is set, matching job_type. Composite foreign keys pin the job
    to its resource's organization, so a job can never reference another tenant's run.
    """

    __tablename__ = "execution_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_run_id", "organization_id"],
            ["agent_runs.id", "agent_runs.organization_id"],
            name="fk_execution_jobs_agent_run_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["team_run_id", "organization_id"],
            ["agent_team_runs.id", "agent_team_runs.organization_id"],
            name="fk_execution_jobs_team_run_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["approval_request_id", "organization_id"],
            ["approval_requests.id", "approval_requests.organization_id"],
            name="fk_execution_jobs_approval_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["evaluation_run_id", "organization_id"],
            ["evaluation_runs.id", "evaluation_runs.organization_id"],
            name="fk_execution_jobs_evaluation_run_organization",
            ondelete="CASCADE",
        ),
        # One job per evaluation run; retries reuse the row.
        UniqueConstraint("evaluation_run_id", name="uq_execution_jobs_evaluation_run"),
        ForeignKeyConstraint(
            ["knowledge_document_id", "organization_id"],
            ["knowledge_documents.id", "knowledge_documents.organization_id"],
            name="fk_execution_jobs_knowledge_document_organization",
            ondelete="CASCADE",
        ),
        CheckConstraint(RESOURCE_CHECK, name="ck_execution_jobs_resource"),
        CheckConstraint(
            "attempt >= 0 AND attempt <= max_attempts", name="ck_execution_jobs_attempt"
        ),
        CheckConstraint("max_attempts >= 1", name="ck_execution_jobs_max_attempts"),
        # One job per run (and per approval); retries reuse the row, they never add one.
        UniqueConstraint("agent_run_id", name="uq_execution_jobs_agent_run"),
        UniqueConstraint("job_type", "team_run_id", name="uq_execution_jobs_team_run_type"),
        UniqueConstraint("approval_request_id", name="uq_execution_jobs_approval"),
        Index("ix_execution_jobs_organization_created", "organization_id", "created_at"),
        # A document is re-ingested many times (re-index, new content): no unique key, but
        # the service never starts a second active job for the same document.
        Index("ix_execution_jobs_knowledge_document", "knowledge_document_id"),
        # Recovery scans: stale running jobs, undelivered queued jobs, due retries.
        Index("ix_execution_jobs_status_heartbeat", "status", "heartbeat_at"),
        Index("ix_execution_jobs_status_next_retry", "status", "next_retry_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    job_type: Mapped[JobType] = mapped_column(string_enum(JobType, "execution_job_type"))
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    team_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    knowledge_document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    evaluation_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[JobStatus] = mapped_column(
        string_enum(JobStatus, "execution_job_status"),
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
    )
    # Attempts started so far; claiming increments it.
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer)
    queue_name: Mapped[str] = mapped_column(String(80))
    # Debugging aid only (hostname:pid:uuid); never used for authorization.
    worker_id: Mapped[str | None] = mapped_column(String(160))
    # Last successful hand-off to Redis; NULL means delivery is still pending.
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def resource_id(self) -> uuid.UUID:
        return (
            self.agent_run_id
            or self.approval_request_id
            or self.team_run_id
            or self.knowledge_document_id
            or self.evaluation_run_id
        )
