from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.jobs.retry import is_retryable, retry_delay
from app.models.jobs import ExecutionJob, JobStatus


class JobInterrupted(BaseException):
    """Stops a run between stages. A BaseException so node-level `except Exception` blocks
    (which turn tool errors into agent failures) cannot swallow it."""


class JobCancelled(JobInterrupted):
    """A user asked to cancel the run; the runtime records a cancelled outcome."""


class JobLost(JobInterrupted):
    """This attempt no longer owns the job (recovery re-queued it); write nothing more."""


SETTLED_STATUS = {
    "completed": JobStatus.COMPLETED,
    # The run pauses for a human; the job that produced the pause is finished.
    "awaiting_approval": JobStatus.COMPLETED,
    "failed": JobStatus.FAILED,
    "cancelled": JobStatus.CANCELLED,
    "retry": JobStatus.RETRYING,
}


@dataclass(frozen=True)
class JobControl:
    """What a runtime needs from the job executing it: attempt number, cooperative
    cancellation and ownership checks, and an atomic way to settle the job."""

    sessions: sessionmaker[Session]
    job_id: UUID
    worker_id: str
    attempt: int
    max_attempts: int
    retry_base_seconds: float

    def _owned(self, job: ExecutionJob | None) -> bool:
        return (
            job is not None
            and job.status == JobStatus.RUNNING
            and job.worker_id == self.worker_id
            and job.attempt == self.attempt
        )

    def ensure_owned(self) -> None:
        with self.sessions() as db:
            if not self._owned(db.get(ExecutionJob, self.job_id)):
                raise JobLost()

    def checkpoint(self) -> None:
        """Called between graph stages: stop if cancelled or no longer the owner."""
        with self.sessions() as db:
            job = db.get(ExecutionJob, self.job_id)
            if not self._owned(job):
                raise JobLost()
            if job.cancellation_requested_at is not None:
                raise JobCancelled()

    def cancel_requested(self) -> bool:
        with self.sessions() as db:
            job = db.get(ExecutionJob, self.job_id)
            return job is not None and job.cancellation_requested_at is not None

    def should_retry(self, code: str | None) -> bool:
        return is_retryable(code) and self.attempt < self.max_attempts

    def settle(
        self,
        db: Session,
        outcome: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> datetime | None:
        """Finish this attempt inside the caller's transaction (which also writes the run), so
        run and job can never disagree. Returns next_retry_at for a retry."""
        job = db.scalar(
            select(ExecutionJob)
            .where(ExecutionJob.id == self.job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not self._owned(job):
            raise JobLost()
        now = datetime.now(UTC)
        job.status = SETTLED_STATUS[outcome]
        job.heartbeat_at = now
        job.error_code = error_code
        job.error_message = error_message
        if outcome == "retry":
            job.next_retry_at = now + timedelta(
                seconds=retry_delay(self.attempt, self.retry_base_seconds)
            )
            # The retry is a new delivery; recovery re-sends it if the delayed message is lost.
            job.enqueued_at = None
            return job.next_retry_at
        job.completed_at = now
        return None
