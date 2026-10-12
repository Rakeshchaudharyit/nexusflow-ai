from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.agents import RunStatus
from app.models.jobs import ExecutionJob, JobStatus, JobType


class ExecutionInfo(BaseModel):
    """Safe view of a run's background job: lifecycle and retry state, no queue internals."""

    job_id: UUID
    job_type: JobType
    status: JobStatus
    attempt: int
    max_attempts: int
    enqueued_at: datetime | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    next_retry_at: datetime | None
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None
    cancellation_requested: bool
    # Persisted but not yet handed to Redis (e.g. Redis was down); recovery will deliver it.
    delivery_pending: bool

    @classmethod
    def of(cls, job: ExecutionJob | None) -> "ExecutionInfo | None":
        if job is None:
            return None
        return cls(
            job_id=job.id,
            job_type=job.job_type,
            status=job.status,
            attempt=job.attempt,
            max_attempts=job.max_attempts,
            enqueued_at=job.enqueued_at,
            started_at=job.started_at,
            heartbeat_at=job.heartbeat_at,
            next_retry_at=job.next_retry_at,
            completed_at=job.completed_at,
            error_code=job.error_code,
            error_message=job.error_message,
            cancellation_requested=job.cancellation_requested_at is not None,
            delivery_pending=job.enqueued_at is None
            and job.status in (JobStatus.QUEUED, JobStatus.RETRYING),
        )


class CancelResponse(BaseModel):
    run_id: UUID
    status: RunStatus
    # True when the run was running: the worker stops at its next stage boundary.
    cancellation_requested: bool
    execution: ExecutionInfo | None
