"""Persisting action decisions: approval requests and (simulated) executions.

Shared by the team graph (immediate ALLOW path, approval requests) and by the approval
continuation, so there is one implementation of each side effect. Callers own the transaction;
these functions only add rows and events to it.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.actions import executors
from app.agents.events import EventStream
from app.models.agents import RunEventStatus, RunEventType
from app.models.approvals import ActionExecution, ApprovalRequest, ExecutionStatus
from app.policies.engine import PolicyDecision

logger = logging.getLogger(__name__)
FAILURE = "The simulated action could not be completed."


def create_approval(
    db: Session,
    events: EventStream,
    *,
    organization_id: UUID,
    team_run_id: UUID,
    team_id: UUID,
    agent_id: UUID,
    user_id: UUID,
    proposal: dict[str, Any],
    policy: PolicyDecision,
    expire_hours: int,
) -> ApprovalRequest:
    now = datetime.now(UTC)
    approval = ApprovalRequest(
        organization_id=organization_id,
        team_run_id=team_run_id,
        team_id=team_id,
        proposed_by_agent_id=agent_id,
        action_type=proposal["action_type"],
        payload=proposal["payload"],
        risk_level=policy.risk_level,
        rule_key=policy.rule_key,
        reason=policy.reason,
        requested_by_user_id=user_id,
        created_at=now,
        expires_at=now + timedelta(hours=expire_hours),
    )
    db.add(approval)
    db.flush()
    events.append(
        db,
        RunEventType.APPROVAL_REQUESTED,
        RunEventStatus.STARTED,
        node="request_approval",
        agent_id=agent_id,
        agent_role="supervisor",
        output_payload={"approval_id": str(approval.id), **policy.as_dict(), **proposal},
    )
    return approval


def perform_action(
    db: Session,
    events: EventStream,
    *,
    organization_id: UUID,
    team_run_id: UUID,
    proposal: dict[str, Any],
    user_id: UUID,
    approval_id: UUID | None,
) -> dict[str, Any]:
    """Run the local simulation once and record it. Returns a JSON-safe outcome."""
    action_type = proposal["action_type"]
    events.append(
        db,
        RunEventType.ACTION_STARTED,
        RunEventStatus.STARTED,
        node="execute_action",
        input_payload={"action_type": action_type, "approval_id": approval_id and str(approval_id)},
    )
    try:
        result = executors.simulate(action_type, proposal["payload"])
        status = ExecutionStatus.COMPLETED
    except Exception as error:
        logger.error("Simulated action %s failed (%s)", action_type, type(error).__name__)
        result = {"simulated": True, "action_type": action_type, "message": FAILURE}
        status = ExecutionStatus.FAILED
    execution = ActionExecution(
        organization_id=organization_id,
        team_run_id=team_run_id,
        approval_request_id=approval_id,
        action_type=action_type,
        payload=proposal["payload"],
        status=status,
        result=result,
        executed_by_user_id=user_id,
    )
    db.add(execution)
    db.flush()
    completed = status == ExecutionStatus.COMPLETED
    events.append(
        db,
        RunEventType.ACTION_COMPLETED if completed else RunEventType.ACTION_FAILED,
        RunEventStatus.COMPLETED if completed else RunEventStatus.FAILED,
        node="execute_action",
        output_payload={"execution_id": str(execution.id), **result},
        error_message=None if completed else FAILURE,
    )
    return {"execution_id": str(execution.id), "status": status.value, **result}
