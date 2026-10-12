"""Persistent job lifecycle. PostgreSQL decides who runs what; Redis only carries job ids."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import case, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.agents.events import EventStream
from app.core.config import Settings
from app.knowledge.lifecycle import lock_document, lock_source, refresh_source, settle_document
from app.models.agents import AgentRun, RunEventStatus, RunEventType, RunStatus
from app.models.approvals import ApprovalRequest, ApprovalStatus
from app.models.evaluation import EvaluationRun, EvaluationRunStatus
from app.models.jobs import ExecutionJob, JobStatus, JobType
from app.models.knowledge import KnowledgeDocument
from app.models.teams import AgentTeamRun
from app.observability.tracer import record_recovery

logger = logging.getLogger(__name__)
WORKER_LOST = "The worker stopped responding during this attempt."
WORKER_LOST_FINAL = "The worker stopped responding and the retry limit was reached."


class JobQueue(Protocol):
    """Transport only: hands a job id to whatever executes it."""

    def send(self, job_id: UUID, delay_seconds: float = 0) -> None: ...


def now() -> datetime:
    return datetime.now(UTC)


def create_job(
    db: Session,
    settings: Settings,
    *,
    organization_id: UUID,
    job_type: JobType,
    agent_run_id: UUID | None = None,
    team_run_id: UUID | None = None,
    approval_request_id: UUID | None = None,
    knowledge_document_id: UUID | None = None,
    evaluation_run_id: UUID | None = None,
) -> ExecutionJob:
    """Add a queued job to the caller's transaction (committed together with its run)."""
    job = ExecutionJob(
        organization_id=organization_id,
        job_type=job_type,
        agent_run_id=agent_run_id,
        team_run_id=team_run_id,
        approval_request_id=approval_request_id,
        knowledge_document_id=knowledge_document_id,
        evaluation_run_id=evaluation_run_id,
        # Microsecond timestamp: a document can get several jobs within one second
        # (upload, then re-index) and "latest job" must still be unambiguous.
        created_at=now(),
        status=JobStatus.QUEUED,
        attempt=0,
        max_attempts=settings.job_max_attempts,
        queue_name=settings.queue_name,
    )
    db.add(job)
    db.flush()
    return job


def deliver(db: Session, queue: JobQueue, job_id: UUID, delay_seconds: float = 0) -> bool:
    """Send a committed job to the queue. On failure the job stays queued with enqueued_at
    NULL, and worker recovery re-sends it: work is never orphaned by a Redis outage."""
    try:
        queue.send(job_id, delay_seconds)
    except Exception as error:
        logger.warning(
            "Queue delivery failed for job %s (%s); recovery will re-send it",
            job_id,
            type(error).__name__,
        )
        return False
    db.execute(
        update(ExecutionJob)
        .where(
            ExecutionJob.id == job_id,
            ExecutionJob.status.in_((JobStatus.QUEUED, JobStatus.RETRYING)),
        )
        .values(enqueued_at=now())
    )
    db.commit()
    return True


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    organization_id: UUID
    job_type: JobType
    attempt: int
    max_attempts: int
    agent_run_id: UUID | None
    team_run_id: UUID | None
    approval_request_id: UUID | None
    knowledge_document_id: UUID | None = None
    evaluation_run_id: UUID | None = None
    created_at: datetime | None = None
    claimed_at: datetime | None = None


def claim(sessions: sessionmaker[Session], job_id: UUID, worker_id: str) -> Claim | None:
    """Atomically move a deliverable job to running. One UPDATE ... WHERE status IN (queued,
    retrying): concurrent claimers serialise on the row and only the first matches, so a
    duplicate or redelivered message can never start a second execution."""
    moment = now()
    with sessions() as db:
        row = db.execute(
            update(ExecutionJob)
            .where(
                ExecutionJob.id == job_id,
                ExecutionJob.status.in_((JobStatus.QUEUED, JobStatus.RETRYING)),
                ExecutionJob.cancellation_requested_at.is_(None),
                ExecutionJob.attempt < ExecutionJob.max_attempts,
                or_(ExecutionJob.next_retry_at.is_(None), ExecutionJob.next_retry_at <= moment),
            )
            .values(
                status=JobStatus.RUNNING,
                attempt=ExecutionJob.attempt + 1,
                worker_id=worker_id,
                started_at=moment,
                heartbeat_at=moment,
                next_retry_at=None,
                error_code=None,
                error_message=None,
            )
            .returning(
                ExecutionJob.id,
                ExecutionJob.organization_id,
                ExecutionJob.job_type,
                ExecutionJob.attempt,
                ExecutionJob.max_attempts,
                ExecutionJob.agent_run_id,
                ExecutionJob.team_run_id,
                ExecutionJob.approval_request_id,
                ExecutionJob.knowledge_document_id,
                ExecutionJob.evaluation_run_id,
                ExecutionJob.created_at,
            )
        ).first()
        db.commit()
    return Claim(*row, claimed_at=moment) if row else None


def heartbeat(sessions: sessionmaker[Session], job_id: UUID, worker_id: str, attempt: int) -> bool:
    """Refresh heartbeat_at for an owned running job. False means ownership was lost."""
    with sessions() as db:
        result = db.execute(
            update(ExecutionJob)
            .where(
                ExecutionJob.id == job_id,
                ExecutionJob.worker_id == worker_id,
                ExecutionJob.attempt == attempt,
                ExecutionJob.status == JobStatus.RUNNING,
            )
            .values(heartbeat_at=now())
        )
        db.commit()
        return result.rowcount == 1


def lock_job_resources(db: Session, job: ExecutionJob):
    """Lock approval -> run -> job, the order every writer uses, and return (run, job).
    A team run's approval (if any) is locked first and reachable as run.approval_locked.
    For a knowledge ingestion job: source -> document -> job, returning (document, job)."""
    if job.job_type == JobType.EVALUATION_RUN:
        evaluation = db.scalar(
            select(EvaluationRun)
            .where(
                EvaluationRun.id == job.evaluation_run_id,
                EvaluationRun.organization_id == job.organization_id,
            )
            .with_for_update()
        )
        locked = db.scalar(
            select(ExecutionJob)
            .where(ExecutionJob.id == job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return evaluation, locked
    if job.job_type == JobType.KNOWLEDGE_INGESTION:
        document = db.get(KnowledgeDocument, job.knowledge_document_id)
        if document is not None:
            source = lock_source(db, job.organization_id, document.source_id)
            document = lock_document(db, job.organization_id, document.id)
            if document is not None:
                document.source_locked = source
        locked = db.scalar(
            select(ExecutionJob)
            .where(ExecutionJob.id == job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return document, locked
    approval = None
    if job.team_run_id is not None:
        approval = db.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.team_run_id == job.team_run_id,
                ApprovalRequest.organization_id == job.organization_id,
            )
            .with_for_update()
        )
    model = AgentRun if job.agent_run_id is not None else AgentTeamRun
    run_id = job.agent_run_id or job.team_run_id
    run = db.scalar(
        select(model)
        .where(model.id == run_id, model.organization_id == job.organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    locked = db.scalar(
        select(ExecutionJob)
        .where(ExecutionJob.id == job.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is not None:
        run.approval_locked = approval
    return run, locked


def run_events(job: ExecutionJob) -> EventStream:
    if job.agent_run_id is not None:
        return EventStream(None, run_id=job.agent_run_id)
    return EventStream(None, team_run_id=job.team_run_id)


def release_attempt(
    db: Session, job: ExecutionJob, run, code: str, message: str, final: str
) -> str:
    """End a running attempt that cannot finish itself (dead worker, infrastructure error):
    cancel it if a cancellation was requested, re-queue it while attempts remain, otherwise
    fail the job and its run. Caller holds the locks from lock_job_resources.
    Returns "cancelled", "requeued" or "failed"."""
    if job.job_type == JobType.KNOWLEDGE_INGESTION:
        return release_ingestion(db, job, run, code, message, final)
    if job.job_type == JobType.EVALUATION_RUN:
        return release_evaluation(job, run, code, message, final)
    moment = now()
    events = run_events(job)
    events.resume(db, job.organization_id)
    events.attempt = job.attempt
    team = job.agent_run_id is None
    if job.cancellation_requested_at is not None:
        job.status = JobStatus.CANCELLED
        job.completed_at = moment
        job.error_code, job.error_message = "cancelled", "The run was cancelled."
        if run is not None and run.status in (RunStatus.RUNNING, RunStatus.QUEUED):
            run.status = RunStatus.CANCELLED
            run.completed_at = moment
            approval = getattr(run, "approval_locked", None)
            if approval is not None and approval.status == ApprovalStatus.PENDING:
                approval.status = ApprovalStatus.CANCELLED
            events.append(
                db,
                RunEventType.TEAM_RUN_CANCELLED if team else RunEventType.RUN_CANCELLED,
                RunEventStatus.FAILED,
                error_message="The run was cancelled.",
            )
        return "cancelled"
    if job.attempt < job.max_attempts:
        job.status = JobStatus.RETRYING
        # The failure was the worker, not the work: the next attempt may start at once.
        job.next_retry_at = moment
        job.enqueued_at = None
        job.error_code, job.error_message = code, message
        if run is not None and run.status == RunStatus.RUNNING:
            run.status = RunStatus.QUEUED
            events.append(
                db,
                RunEventType.RETRY_SCHEDULED,
                RunEventStatus.FAILED,
                output_payload={
                    "error_code": code,
                    "attempt": job.attempt,
                    "max_attempts": job.max_attempts,
                    "next_retry_at": job.next_retry_at,
                },
                error_message=message,
            )
        return "requeued"
    job.status = JobStatus.FAILED
    job.completed_at = moment
    job.error_code, job.error_message = code, final
    if run is not None and run.status in (RunStatus.RUNNING, RunStatus.QUEUED):
        run.status = RunStatus.FAILED
        run.completed_at = moment
        run.error_code, run.error_message = code, final
        events.append(
            db,
            RunEventType.TEAM_RUN_FAILED if team else RunEventType.RUN_FAILED,
            RunEventStatus.FAILED,
            output_payload={"error_code": code},
            error_message=final,
        )
    return "failed"


def release_ingestion(
    db: Session, job: ExecutionJob, document, code: str, message: str, final: str
) -> str:
    """release_attempt for knowledge ingestion: no run or events, the document carries state."""
    moment = now()
    if job.cancellation_requested_at is not None:
        outcome = "cancelled"
        job.status, job.completed_at = JobStatus.CANCELLED, moment
        job.error_code, job.error_message = "cancelled", "Ingestion was cancelled."
    elif job.attempt < job.max_attempts:
        outcome = "requeued"
        job.status, job.next_retry_at, job.enqueued_at = JobStatus.RETRYING, moment, None
        job.error_code, job.error_message = code, message
    else:
        outcome = "failed"
        job.status, job.completed_at = JobStatus.FAILED, moment
        job.error_code, job.error_message = code, final
    if document is not None:
        settle_document(
            document,
            {"requeued": "retry"}.get(outcome, outcome),
            job.error_code,
            job.error_message,
        )
        source = getattr(document, "source_locked", None)
        if source is not None:
            refresh_source(db, source)
    return outcome


def release_evaluation(job: ExecutionJob, evaluation, code: str, message: str, final: str) -> str:
    """release_attempt for an evaluation job: the evaluation run carries the state. A retry
    resumes after the cases that already have results."""
    moment = now()
    if job.cancellation_requested_at is not None:
        job.status, job.completed_at = JobStatus.CANCELLED, moment
        job.error_code, job.error_message = "cancelled", "The evaluation was cancelled."
        if evaluation is not None:
            evaluation.status, evaluation.completed_at = EvaluationRunStatus.CANCELLED, moment
        return "cancelled"
    if job.attempt < job.max_attempts:
        job.status, job.next_retry_at, job.enqueued_at = JobStatus.RETRYING, moment, None
        job.error_code, job.error_message = code, message
        return "requeued"
    job.status, job.completed_at = JobStatus.FAILED, moment
    job.error_code, job.error_message = code, final
    if evaluation is not None:
        evaluation.status, evaluation.completed_at = EvaluationRunStatus.FAILED, moment
        evaluation.error_code, evaluation.error_message = code, final
    return "failed"


@dataclass
class RecoveryReport:
    requeued: list[UUID]
    failed: list[UUID]
    redeliver: list[tuple[UUID, float]]
    cancelled: list[UUID] = field(default_factory=list)


def recover(sessions: sessionmaker[Session], settings: Settings) -> RecoveryReport:
    """Find work that no worker will finish and make it deliverable again.

    1. Running jobs whose heartbeat is stale (worker died or froze): retry or fail.
    2. Queued jobs never handed to Redis, or whose message is older than the redelivery window
       (Redis restarted and lost it): re-send.
    3. Retrying jobs whose delayed message never arrived: re-send.
    Duplicate sends are harmless: claim() admits only one execution.
    """
    moment = now()
    stale_before = moment - timedelta(seconds=settings.job_stale_after_seconds)
    redeliver_before = moment - timedelta(seconds=settings.job_redeliver_after_seconds)
    report = RecoveryReport([], [], [])
    with sessions() as db:
        stale = db.scalars(
            select(ExecutionJob).where(
                ExecutionJob.status == JobStatus.RUNNING,
                or_(
                    ExecutionJob.heartbeat_at < stale_before,
                    ExecutionJob.heartbeat_at.is_(None),
                ),
            )
        ).all()
    for candidate in stale:
        with sessions() as db:
            run, job = lock_job_resources(db, candidate)
            heartbeat_at = job.heartbeat_at
            if heartbeat_at is not None and heartbeat_at.tzinfo is None:
                heartbeat_at = heartbeat_at.replace(tzinfo=UTC)
            if job.status != JobStatus.RUNNING or (
                heartbeat_at is not None and heartbeat_at >= stale_before
            ):
                db.rollback()
                continue
            lost_attempt = {
                "organization_id": job.organization_id,
                "agent_run_id": job.agent_run_id,
                "team_run_id": job.team_run_id,
                "attempt": job.attempt,
                "max_attempts": job.max_attempts,
                "started_at": job.started_at,
                "heartbeat_at": job.heartbeat_at,
            }
            traced = job.job_type in (
                JobType.SINGLE_AGENT_RUN,
                JobType.TEAM_RUN,
                JobType.APPROVAL_ACTION,
            )
            outcome = release_attempt(db, job, run, "worker_lost", WORKER_LOST, WORKER_LOST_FINAL)
            db.commit()
            if traced:
                record_recovery(sessions, outcome=outcome, **lost_attempt)
            logger.warning(
                "Recovered stale job %s (org %s, type %s, attempt %s): %s",
                job.id,
                job.organization_id,
                job.job_type,
                job.attempt,
                outcome,
            )
            if outcome == "requeued":
                report.requeued.append(job.id)
                report.redeliver.append((job.id, 0.0))
            elif outcome == "failed":
                report.failed.append(job.id)
            else:
                report.cancelled.append(job.id)
    with sessions() as db:
        lost = db.scalars(
            select(ExecutionJob.id).where(
                or_(
                    (ExecutionJob.status == JobStatus.QUEUED)
                    & or_(
                        ExecutionJob.enqueued_at.is_(None),
                        ExecutionJob.enqueued_at < redeliver_before,
                    ),
                    (ExecutionJob.status == JobStatus.RETRYING)
                    & (ExecutionJob.next_retry_at <= moment)
                    & or_(
                        ExecutionJob.enqueued_at.is_(None),
                        ExecutionJob.next_retry_at < redeliver_before,
                    ),
                ),
                ExecutionJob.cancellation_requested_at.is_(None),
            )
        ).all()
    known = {job_id for job_id, _ in report.redeliver}
    report.redeliver.extend((job_id, 0.0) for job_id in lost if job_id not in known)
    return report


# An approval action always follows its team run's job; break created_at ties explicitly.
LATEST_FIRST = (
    ExecutionJob.created_at.desc(),
    case((ExecutionJob.job_type == JobType.APPROVAL_ACTION, 0), else_=1),
    ExecutionJob.id,
)


def latest_job(db: Session, organization_id: UUID, **resource) -> ExecutionJob | None:
    ((column, value),) = resource.items()
    return db.scalar(
        select(ExecutionJob)
        .where(
            getattr(ExecutionJob, column) == value,
            ExecutionJob.organization_id == organization_id,
        )
        .order_by(*LATEST_FIRST)
        .limit(1)
    )
