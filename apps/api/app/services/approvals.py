"""Approval inbox and explicit continuation of paused team runs.

A team run that proposes an action needing approval ends its job as `awaiting_approval`.
Reviewing it here is an application-level continuation, not a LangGraph checkpoint resume.
Approving records the decision and queues an `approval_action` job in one transaction (M7);
the worker then runs the single simulated action and completes the run under row locks on
the approval and the run. A second reviewer blocks on the lock and finds the request no
longer pending; a redelivered job finds the execution already recorded. The action runs once.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.actions.service import perform_action
from app.agents.events import EventStream
from app.core.config import Settings
from app.core.errors import APIError
from app.jobs.control import JobControl
from app.jobs.service import JobQueue, create_job, deliver
from app.memory.writer import remember_approval
from app.models.agents import Agent, RunEventStatus, RunEventType, RunStatus
from app.models.approvals import ActionExecution, ApprovalRequest, ApprovalStatus
from app.models.jobs import JobType
from app.models.observability import SpanStatus, SpanType
from app.models.teams import AgentTeam, AgentTeamRun
from app.observability.tracer import Tracer
from app.policies.engine import Decision, RiskLevel, evaluate
from app.schemas.approvals import ApprovalResponse, ExecutionResponse
from app.services.auth import utc


def locked_approval(db: Session, organization_id: UUID, approval_id: UUID) -> ApprovalRequest:
    approval = db.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.organization_id == organization_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if approval is None:
        raise APIError(404, "approval_not_found", "Approval not found.")
    return approval


def locked_run(db: Session, approval: ApprovalRequest) -> AgentTeamRun:
    return db.scalar(
        select(AgentTeamRun)
        .where(
            AgentTeamRun.id == approval.team_run_id,
            AgentTeamRun.organization_id == approval.organization_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def settle_run(
    db: Session,
    run: AgentTeamRun,
    events: EventStream,
    *,
    action_status: str,
    approval: ApprovalRequest,
    outcome: dict[str, Any] | None,
    error: tuple[str, str] | None = None,
) -> None:
    """Finish a paused run after its approval resolved, with one terminal event."""
    failed = action_status == "failed" or error is not None
    output = dict(run.final_output or {})
    action = {**output.get("action", {}), "status": action_status}
    if outcome:
        action |= {"execution_id": outcome["execution_id"], "message": outcome["message"]}
    output["action"] = action
    run.final_output = to_jsonable_python(output)
    snapshot = dict(run.state_snapshot or {})
    snapshot["action_result"] = outcome
    run.state_snapshot = to_jsonable_python(snapshot)
    run.status = RunStatus.FAILED if failed else RunStatus.COMPLETED
    run.completed_at = datetime.now(UTC)
    if failed:
        run.error_code, run.error_message = error or ("action_failed", outcome["message"])
    events.append(
        db,
        RunEventType.TEAM_RUN_FAILED if failed else RunEventType.TEAM_RUN_COMPLETED,
        RunEventStatus.FAILED if failed else RunEventStatus.COMPLETED,
        output_payload={"approval_id": str(approval.id), "action": action},
        error_message=run.error_message if failed else None,
    )


def expire_if_due(db: Session, approval: ApprovalRequest) -> bool:
    """Lazily expire an overdue request; the paused run completes without its action."""
    if approval.status != ApprovalStatus.PENDING or utc(approval.expires_at) > datetime.now(UTC):
        return False
    run = locked_run(db, approval)
    approval.status = ApprovalStatus.EXPIRED
    if run is not None and run.status == RunStatus.AWAITING_APPROVAL:
        events = EventStream(None, team_run_id=run.id).resume(db, run.organization_id)
        events.append(
            db,
            RunEventType.APPROVAL_EXPIRED,
            RunEventStatus.FAILED,
            node="human_review",
            output_payload={"approval_id": str(approval.id)},
            error_message="The approval expired before review.",
        )
        settle_run(db, run, events, action_status="expired", approval=approval, outcome=None)
    return True


def review(
    db: Session,
    organization_id: UUID,
    approval_id: UUID,
    reviewer_id: UUID,
    approve: bool,
    comment: str | None,
    settings: Settings,
    queue: JobQueue,
) -> ApprovalResponse:
    approval = locked_approval(db, organization_id, approval_id)
    if expire_if_due(db, approval):
        db.commit()
        raise APIError(409, "approval_expired", "This approval has expired.")
    if approval.status != ApprovalStatus.PENDING:
        raise APIError(409, "approval_not_pending", "This approval has already been decided.")
    run = locked_run(db, approval)
    if run is None or run.status != RunStatus.AWAITING_APPROVAL:
        raise APIError(409, "run_not_awaiting_approval", "The team run is not awaiting approval.")
    # Policy is re-evaluated at decision time; a rule tightened to DENY cannot be approved.
    if approve and evaluate(approval.action_type, validated_result=True).decision == Decision.DENY:
        raise APIError(409, "policy_denied", "Current policy prohibits this action.")
    now = datetime.now(UTC)
    approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    approval.reviewed_by_user_id = reviewer_id
    approval.reviewed_at = now
    approval.review_comment = comment
    events = EventStream(None, team_run_id=run.id).resume(db, organization_id)
    events.append(
        db,
        RunEventType.APPROVAL_APPROVED if approve else RunEventType.APPROVAL_REJECTED,
        RunEventStatus.COMPLETED if approve else RunEventStatus.FAILED,
        node="human_review",
        output_payload={
            "approval_id": str(approval.id),
            "reviewed_by_user_id": str(reviewer_id),
            "comment": comment,
        },
    )
    if not approve:
        # Rejection executes nothing, so it completes the run right here.
        settle_run(db, run, events, action_status="rejected", approval=approval, outcome=None)
        db.commit()
        tracer = Tracer(organization_id=organization_id, team_run_id=run.id)
        tracer.add(
            SpanType.APPROVAL,
            "Approval rejected",
            status=SpanStatus.FAILED,
            parent=None,
            metadata={"action_type": approval.action_type, "decision": "rejected"},
        )
        tracer.flush(db=db)  # best effort, after the decision is committed
        return approval_response(db, approval)
    # The decision and the job that will act on it commit together; the worker runs the action.
    run.status = RunStatus.QUEUED
    job = create_job(
        db,
        settings,
        organization_id=organization_id,
        job_type=JobType.APPROVAL_ACTION,
        team_run_id=run.id,
        approval_request_id=approval.id,
    )
    db.commit()
    deliver(db, queue, job.id)
    # An inline queue may already have executed the job in another session.
    db.expire_all()
    return approval_response(db, db.get(ApprovalRequest, approval.id))


def execute_approved_action(
    sessions: sessionmaker[Session],
    control: JobControl,
    organization_id: UUID,
    approval_id: UUID,
    memory_settings: Settings | None = None,
    tracer: Tracer | None = None,
) -> None:
    """Worker side of an approval: run the persisted payload once and complete the run.

    Approval, run and job are locked (in that order) for the whole transaction. A redelivered
    or retried job finds the execution already recorded and only finishes bookkeeping, so the
    unique constraints on action_executions are never what saves the day, just the backstop.
    """
    with sessions() as db:
        approval = locked_approval(db, organization_id, approval_id)
        run = locked_run(db, approval)
        events = EventStream(None, team_run_id=approval.team_run_id).resume(db, organization_id)
        events.attempt = control.attempt
        existing = db.scalar(
            select(ActionExecution).where(
                ActionExecution.approval_request_id == approval.id,
                ActionExecution.organization_id == organization_id,
            )
        )
        if run is None or run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
            control.settle(db, "cancelled", "run_not_runnable", "The team run is no longer active.")
            db.commit()
            return
        if approval.status != ApprovalStatus.APPROVED:
            control.settle(db, "failed", "approval_not_approved", "The approval is not approved.")
            db.commit()
            return
        if tracer is not None:
            tracer.add(
                SpanType.APPROVAL,
                "Approval approved",
                metadata={
                    "action_type": approval.action_type,
                    "risk_level": approval.risk_level.value,
                    "decision": "approved",
                },
            )
        action_span = (
            tracer.open(SpanType.ACTION, f"Action · {approval.action_type}")
            if tracer is not None
            else None
        )
        if existing is not None:
            outcome = {
                "execution_id": str(existing.id),
                "status": existing.status.value,
                **existing.result,
            }
        elif evaluate(approval.action_type, validated_result=True).decision == Decision.DENY:
            # Policy is re-checked when the action is about to run, not only at review time.
            denied = ("policy_denied", "Current policy prohibits this action.")
            if tracer is not None:
                tracer.close(
                    action_span, SpanStatus.FAILED, error_code=denied[0], error_message=denied[1]
                )
            settle_run(
                db,
                run,
                events,
                action_status="denied",
                approval=approval,
                outcome=None,
                error=denied,
            )
            control.settle(db, "failed", *denied)
            db.commit()
            return
        else:
            # The exact payload persisted at request time; reviewers cannot edit it.
            outcome = perform_action(
                db,
                events,
                organization_id=organization_id,
                team_run_id=run.id,
                proposal={"action_type": approval.action_type, "payload": approval.payload},
                user_id=approval.reviewed_by_user_id,
                approval_id=approval.id,
            )
        settle_run(
            db, run, events, action_status=outcome["status"], approval=approval, outcome=outcome
        )
        failed = outcome["status"] == "failed"
        if tracer is not None:
            tracer.close(
                action_span,
                SpanStatus.FAILED if failed else SpanStatus.COMPLETED,
                error_code="action_failed" if failed else None,
                metadata={
                    "action_type": approval.action_type,
                    "status": outcome["status"],
                    "reused_execution": existing is not None,
                    "simulated": True,
                },
            )
        if not failed and memory_settings is not None and run.thread_id is not None:
            remember_approval(
                db,
                memory_settings,
                events,
                organization_id=organization_id,
                thread_id=run.thread_id,
                team_id=run.team_id,
                approval_id=approval.id,
                action_type=approval.action_type,
                reviewer_id=approval.reviewed_by_user_id,
                decided_at=approval.reviewed_at,
            )
        control.settle(
            db,
            "failed" if failed else "completed",
            "action_failed" if failed else None,
            outcome["message"] if failed else None,
        )
        db.commit()


def approval_response(db: Session, approval: ApprovalRequest) -> ApprovalResponse:
    org = approval.organization_id
    execution = db.scalar(
        select(ActionExecution).where(
            ActionExecution.approval_request_id == approval.id,
            ActionExecution.organization_id == org,
        )
    )
    return ApprovalResponse(
        **{column.name: getattr(approval, column.name) for column in ApprovalRequest.__table__.c},
        team_name=db.scalar(
            select(AgentTeam.name).where(
                AgentTeam.id == approval.team_id, AgentTeam.organization_id == org
            )
        ),
        agent_name=db.scalar(
            select(Agent.name).where(
                Agent.id == approval.proposed_by_agent_id, Agent.organization_id == org
            )
        ),
        objective=db.scalar(
            select(AgentTeamRun.objective).where(
                AgentTeamRun.id == approval.team_run_id, AgentTeamRun.organization_id == org
            )
        ),
        team_run_status=db.scalar(
            select(AgentTeamRun.status).where(
                AgentTeamRun.id == approval.team_run_id, AgentTeamRun.organization_id == org
            )
        ),
        execution=ExecutionResponse.model_validate(execution) if execution else None,
    )


def get_approval(db: Session, organization_id: UUID, approval_id: UUID) -> ApprovalResponse:
    approval = locked_approval(db, organization_id, approval_id)
    expire_if_due(db, approval)
    db.commit()
    return approval_response(db, approval)


def list_approvals(
    db: Session,
    organization_id: UUID,
    status: ApprovalStatus | None,
    risk_level: RiskLevel | None,
    team_run_id: UUID | None,
    limit: int,
) -> list[ApprovalResponse]:
    overdue = db.scalars(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.organization_id == organization_id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
            ApprovalRequest.expires_at <= datetime.now(UTC),
        )
        .order_by(ApprovalRequest.id)
        .with_for_update()
    ).all()
    for approval in overdue:
        expire_if_due(db, approval)
    db.commit()
    # Approvals raised by evaluation runs (M10) never reach the reviewers' inbox.
    query = (
        select(ApprovalRequest)
        .join(
            AgentTeamRun,
            (AgentTeamRun.id == ApprovalRequest.team_run_id)
            & (AgentTeamRun.organization_id == ApprovalRequest.organization_id),
        )
        .where(
            ApprovalRequest.organization_id == organization_id,
            AgentTeamRun.evaluation_run_id.is_(None),
        )
    )
    for column, value in (
        (ApprovalRequest.status, status),
        (ApprovalRequest.risk_level, risk_level),
        (ApprovalRequest.team_run_id, team_run_id),
    ):
        if value is not None:
            query = query.where(column == value)
    rows = db.scalars(
        query.order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id).limit(limit)
    )
    return [approval_response(db, approval) for approval in rows]


def run_action(db: Session, organization_id: UUID, team_run_id: UUID) -> dict[str, Any] | None:
    """Approval and execution attached to a team run, for run responses."""
    approval = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.team_run_id == team_run_id,
            ApprovalRequest.organization_id == organization_id,
        )
    )
    execution = db.scalar(
        select(ActionExecution).where(
            ActionExecution.team_run_id == team_run_id,
            ActionExecution.organization_id == organization_id,
        )
    )
    if approval is None and execution is None:
        return None
    return {
        "approval_id": approval.id if approval else None,
        "approval_status": approval.status if approval else None,
        "execution": ExecutionResponse.model_validate(execution) if execution else None,
    }
