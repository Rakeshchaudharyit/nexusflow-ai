"""Cooperative cancellation. Workers are never killed: a queued job is cancelled immediately, a
running one is flagged and stops at its next graph stage, and a run awaiting approval closes
its pending request so a later approval cannot execute anything."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.events import EventStream
from app.core.errors import APIError
from app.jobs.service import latest_job
from app.models.agents import AgentRun, RunEventStatus, RunEventType, RunStatus
from app.models.approvals import ApprovalRequest, ApprovalStatus
from app.models.identity import OrganizationMembership, Role
from app.models.jobs import ACTIVE_JOB_STATUSES, ExecutionJob, JobStatus
from app.models.teams import AgentTeamRun
from app.schemas.jobs import CancelResponse, ExecutionInfo
from app.services.approvals import expire_if_due

TERMINAL = (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED)
CANCELLED = "The run was cancelled."


def authorize(membership: OrganizationMembership, run) -> None:
    """Owners and admins may cancel any run in the organization; members only their own."""
    if membership.role in (Role.OWNER, Role.ADMIN):
        return
    if run.created_by_user_id != membership.user_id:
        raise APIError(403, "forbidden", "You can only cancel runs you started.")


def active_jobs(db: Session, organization_id: UUID, **resource) -> list[ExecutionJob]:
    ((column, value),) = resource.items()
    return list(
        db.scalars(
            select(ExecutionJob)
            .where(
                getattr(ExecutionJob, column) == value,
                ExecutionJob.organization_id == organization_id,
                ExecutionJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .order_by(ExecutionJob.id)
            .with_for_update()
        )
    )


def stop(run, jobs: list[ExecutionJob], events: EventStream, db: Session, event: RunEventType):
    """Cancel a run that is not executing right now (queued, retry-waiting or paused)."""
    moment = datetime.now(UTC)
    for job in jobs:
        job.status = JobStatus.CANCELLED
        job.cancellation_requested_at = job.cancellation_requested_at or moment
        job.completed_at = moment
        job.error_code, job.error_message = "cancelled", CANCELLED
    run.status = RunStatus.CANCELLED
    run.completed_at = moment
    events.resume(db, run.organization_id)
    events.append(db, event, RunEventStatus.FAILED, error_message=CANCELLED)


def request(jobs: list[ExecutionJob]) -> bool:
    moment = datetime.now(UTC)
    flagged = False
    for job in jobs:
        if job.status == JobStatus.RUNNING:
            job.cancellation_requested_at = job.cancellation_requested_at or moment
            flagged = True
    return flagged


def cancel_agent_run(
    db: Session, membership: OrganizationMembership, run_id: UUID
) -> CancelResponse:
    organization_id = membership.organization_id
    # Lock order everywhere: (approval ->) run -> job.
    run = db.scalar(
        select(AgentRun)
        .where(AgentRun.id == run_id, AgentRun.organization_id == organization_id)
        .with_for_update()
    )
    if run is None:
        raise APIError(404, "run_not_found", "Run not found.")
    authorize(membership, run)
    if run.status in TERMINAL:
        raise APIError(409, "run_not_cancellable", f"The run is already {run.status.value}.")
    jobs = active_jobs(db, organization_id, agent_run_id=run.id)
    flagged = False
    if run.status == RunStatus.RUNNING and any(j.status == JobStatus.RUNNING for j in jobs):
        flagged = request(jobs)
    else:
        stop(run, jobs, EventStream(None, run_id=run.id), db, RunEventType.RUN_CANCELLED)
    db.commit()
    return CancelResponse(
        run_id=run.id,
        status=run.status,
        cancellation_requested=flagged,
        execution=ExecutionInfo.of(latest_job(db, organization_id, agent_run_id=run.id)),
    )


def cancel_team_run(
    db: Session, membership: OrganizationMembership, run_id: UUID
) -> CancelResponse:
    organization_id = membership.organization_id
    approval = db.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.team_run_id == run_id,
            ApprovalRequest.organization_id == organization_id,
        )
        .with_for_update()
    )
    run = db.scalar(
        select(AgentTeamRun)
        .where(AgentTeamRun.id == run_id, AgentTeamRun.organization_id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise APIError(404, "team_run_not_found", "Team run not found.")
    authorize(membership, run)
    if approval is not None and expire_if_due(db, approval):
        db.commit()  # an overdue approval has just completed the run without its action
    if run.status in TERMINAL:
        db.commit()
        raise APIError(409, "run_not_cancellable", f"The team run is already {run.status.value}.")
    jobs = active_jobs(db, organization_id, team_run_id=run.id)
    flagged = False
    if run.status == RunStatus.RUNNING and any(j.status == JobStatus.RUNNING for j in jobs):
        flagged = request(jobs)
    else:
        if approval is not None and approval.status == ApprovalStatus.PENDING:
            # A later approve finds the request closed and executes nothing.
            approval.status = ApprovalStatus.CANCELLED
        stop(
            run,
            jobs,
            EventStream(None, team_run_id=run.id),
            db,
            RunEventType.TEAM_RUN_CANCELLED,
        )
    db.commit()
    return CancelResponse(
        run_id=run.id,
        status=run.status,
        cancellation_requested=flagged,
        execution=ExecutionInfo.of(latest_job(db, organization_id, team_run_id=run.id)),
    )
