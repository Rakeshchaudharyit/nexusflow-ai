import logging
import os
import socket
import threading
import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.agents.errors import AgentRuntimeError
from app.agents.runtime import AgentRuntime
from app.core.config import Settings
from app.jobs import service
from app.jobs.control import JobControl, JobInterrupted
from app.knowledge.ingestion import KnowledgeIngestor
from app.models.jobs import ExecutionJob, JobStatus, JobType
from app.models.observability import SpanStatus, SpanType
from app.observability.tracer import Tracer
from app.services.approvals import execute_approved_action
from app.teams.runtime import TeamRuntime

logger = logging.getLogger(__name__)
JOB_LABELS = {
    JobType.SINGLE_AGENT_RUN: "agent run",
    JobType.TEAM_RUN: "team run",
    JobType.APPROVAL_ACTION: "approved action",
}


def new_worker_id(prefix: str = "worker") -> str:
    """hostname:pid:random — for debugging which process ran an attempt, nothing more."""
    return f"{prefix}:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class Heartbeat:
    """Refreshes heartbeat_at every `interval` seconds on a daemon thread while a job runs."""

    def __init__(self, sessions: sessionmaker[Session], control: JobControl, interval: float):
        self._sessions = sessions
        self._control = control
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, name="job-heartbeat", daemon=True)

    def _beat(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                owned = service.heartbeat(
                    self._sessions,
                    self._control.job_id,
                    self._control.worker_id,
                    self._control.attempt,
                )
            except Exception as error:
                logger.warning(
                    "Heartbeat failed for job %s (%s)", self._control.job_id, type(error).__name__
                )
                continue
            if not owned:
                # The run notices at its next checkpoint or event write and stops itself.
                logger.warning(
                    "Job %s attempt %s lost ownership", self._control.job_id, self._control.attempt
                )
                return

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=self._interval + 1)


class JobExecutor:
    """Runs one persisted job: claim, heartbeat, execute through the existing runtimes, and
    hand any scheduled retry back to the queue. Shared by the worker and the inline mode."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        settings: Settings,
        agent_runtime: AgentRuntime,
        team_runtime: TeamRuntime,
        queue: service.JobQueue | None = None,
        worker_id: str | None = None,
        knowledge: KnowledgeIngestor | None = None,
        evaluations=None,
    ):
        self._sessions = sessions
        self._settings = settings
        self._agents = agent_runtime
        self._teams = team_runtime
        self._knowledge = knowledge
        # M10: EvaluationRunner (set after construction: it executes child runs through
        # this executor).
        self.evaluations = evaluations
        self.queue = queue
        self.worker_id = worker_id or new_worker_id()

    @property
    def sessions(self) -> sessionmaker[Session]:
        return self._sessions

    def run(self, job_id: UUID) -> JobStatus | None:
        claim = service.claim(self._sessions, job_id, self.worker_id)
        if claim is None:
            # Duplicate delivery, cancelled, already finished, or a retry that is not due yet.
            logger.info("Job %s not claimable by %s; skipping", job_id, self.worker_id)
            return None
        control = JobControl(
            sessions=self._sessions,
            job_id=claim.job_id,
            worker_id=self.worker_id,
            attempt=claim.attempt,
            max_attempts=claim.max_attempts,
            retry_base_seconds=self._settings.job_retry_base_seconds,
        )
        context = {
            "job_id": str(claim.job_id),
            "org_id": str(claim.organization_id),
            "job_type": claim.job_type.value,
            **(
                {"document_id": str(claim.knowledge_document_id)}
                if claim.knowledge_document_id
                else {"run_id": str(claim.agent_run_id or claim.team_run_id)}
            ),
            "attempt": claim.attempt,
        }
        logger.info("Job started %s", context)
        tracer = self._tracer(claim)
        worker_span = None
        if tracer is not None:
            worker_span = tracer.open(
                SpanType.WORKER,
                f"Attempt {claim.attempt} · {JOB_LABELS[claim.job_type]}",
                parent=None,
            )
            worker_span.metadata.update(
                {
                    "job_id": str(claim.job_id),
                    "job_type": claim.job_type.value,
                    "attempt": claim.attempt,
                    "max_attempts": claim.max_attempts,
                    "worker_id": self.worker_id,
                    "queue_wait_ms": tracer.queue_wait_ms,
                }
            )
        lost = False
        with Heartbeat(self._sessions, control, self._settings.worker_heartbeat_seconds):
            try:
                if claim.job_type == JobType.SINGLE_AGENT_RUN:
                    self._agents.execute(claim.agent_run_id, control, tracer=tracer)
                elif claim.job_type == JobType.TEAM_RUN:
                    self._teams.execute(claim.team_run_id, control, tracer=tracer)
                elif claim.job_type == JobType.KNOWLEDGE_INGESTION:
                    if self._knowledge is None:
                        raise AgentRuntimeError(
                            "Knowledge ingestion is not configured.", code="ingestion_failed"
                        )
                    self._knowledge.execute(claim.knowledge_document_id, control)
                elif claim.job_type == JobType.EVALUATION_RUN:
                    if self.evaluations is None:
                        raise AgentRuntimeError(
                            "Evaluation is not configured.", code="evaluation_failed"
                        )
                    self.evaluations.execute(claim.evaluation_run_id, control)
                else:
                    execute_approved_action(
                        self._sessions,
                        control,
                        claim.organization_id,
                        claim.approval_request_id,
                        self._settings,
                        tracer=tracer,
                    )
            except JobInterrupted:
                lost = True
                logger.warning("Job %s attempt %s stopped: ownership lost", job_id, claim.attempt)
            except AgentRuntimeError as error:
                # The run refused to start (e.g. cancelled meanwhile): permanent, run untouched.
                self._fail_job(control, error.code, error.message)
            except Exception as error:
                # Infrastructure fault outside the runtime's own handling (e.g. a dropped DB
                # connection): release the attempt now instead of waiting for stale recovery.
                logger.error("Job %s failed in the executor (%s)", job_id, type(error).__name__)
                self._release(claim.job_id, control)
        if tracer is not None:
            self._finish_trace(tracer, worker_span, claim, lost)
        return self._after(claim.job_id, context)

    def _tracer(self, claim: service.Claim) -> Tracer | None:
        """Agent runs, team runs and approval continuations are traced (one trace per run)."""
        if claim.job_type not in JOB_LABELS:
            return None
        tracer = Tracer(
            organization_id=claim.organization_id,
            agent_run_id=claim.agent_run_id,
            team_run_id=claim.team_run_id,
            attempt=claim.attempt,
        )
        if claim.attempt == 1 and claim.created_at and claim.claimed_at:
            created = claim.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            # Real queue wait: worker claim time minus job creation (both persisted UTC).
            tracer.queue_wait_ms = max(
                0, round((claim.claimed_at - created).total_seconds() * 1000)
            )
        return tracer

    def _finish_trace(self, tracer: Tracer, worker_span, claim: service.Claim, lost: bool) -> None:
        """Close the attempt span from the job's settled state, add a retry span when the job
        was re-queued, and flush. Best effort: never raises."""
        try:
            with self._sessions() as db:
                job = db.get(ExecutionJob, claim.job_id)
                status, code = job.status, job.error_code
                message, next_retry_at = job.error_message, job.next_retry_at
            span_status = {
                JobStatus.COMPLETED: SpanStatus.COMPLETED,
                JobStatus.CANCELLED: SpanStatus.CANCELLED,
                JobStatus.RUNNING: SpanStatus.LOST,
            }.get(status, SpanStatus.FAILED)
            if lost:
                span_status = SpanStatus.LOST
            failed = span_status == SpanStatus.FAILED
            tracer.close(
                worker_span,
                span_status if status != JobStatus.RETRYING else SpanStatus.FAILED,
                error_code=code if failed or status == JobStatus.RETRYING else None,
                error_message=message if failed or status == JobStatus.RETRYING else None,
                metadata={"job_status": status.value},
            )
            if status == JobStatus.RETRYING:
                retry_at = next_retry_at
                if retry_at is not None and retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delay = (
                    max(0, round((retry_at - datetime.now(UTC)).total_seconds() * 1000))
                    if retry_at
                    else None
                )
                tracer.add(
                    SpanType.RETRY,
                    f"Retry scheduled after attempt {claim.attempt}",
                    parent=None,
                    status=SpanStatus.FAILED,
                    error_code=code,
                    error_message=message,
                    metadata={
                        "attempt": claim.attempt,
                        "next_attempt": claim.attempt + 1,
                        "max_attempts": claim.max_attempts,
                        "retry_delay_ms": delay,
                        "reason": "transient failure",
                    },
                )
                tracer.retries += 1
        except Exception as error:
            logger.warning(
                "Could not finish trace for job %s (%s)", claim.job_id, type(error).__name__
            )
        tracer.flush(self._sessions)

    def _fail_job(self, control: JobControl, code: str, message: str) -> None:
        try:
            with self._sessions() as db:
                control.settle(db, "failed", code, message)
                db.commit()
        except JobInterrupted:
            pass  # someone else (a cancellation) already settled it

    def _release(self, job_id: UUID, control: JobControl) -> None:
        try:
            with self._sessions() as db:
                job = db.get(ExecutionJob, job_id)
                run, job = service.lock_job_resources(db, job)
                if job.status != JobStatus.RUNNING or job.worker_id != control.worker_id:
                    db.rollback()
                    return
                service.release_attempt(
                    db,
                    job,
                    run,
                    "worker_error",
                    "The worker hit an infrastructure error during this attempt.",
                    "The worker hit an infrastructure error and the retry limit was reached.",
                )
                db.commit()
        except Exception as error:
            logger.error(
                "Could not release job %s (%s); stale recovery will", job_id, type(error).__name__
            )

    def _after(self, job_id: UUID, context: dict) -> JobStatus | None:
        with self._sessions() as db:
            job = db.get(ExecutionJob, job_id)
            status, next_retry_at = job.status, job.next_retry_at
            logger.info("Job finished %s status=%s error=%s", context, status.value, job.error_code)
            if status == JobStatus.RETRYING and self.queue is not None:
                if next_retry_at.tzinfo is None:
                    next_retry_at = next_retry_at.replace(tzinfo=UTC)
                delay = max((next_retry_at - datetime.now(UTC)).total_seconds(), 0)
                service.deliver(db, self.queue, job_id, delay)
        return status
