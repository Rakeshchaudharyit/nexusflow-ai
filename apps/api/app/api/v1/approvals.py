from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import (
    CurrentMembership,
    CurrentUser,
    Database,
    JobQueueDep,
    require_organization_role,
)
from app.models.approvals import ApprovalStatus
from app.models.identity import OrganizationMembership, Role
from app.policies.engine import RiskLevel
from app.schemas.approvals import ApprovalResponse, ReviewRequest
from app.services import approvals as service

router = APIRouter(prefix="/approvals", tags=["human approvals"])
# Membership and role are re-read from PostgreSQL on every request (M2 dependency).
Reviewer = Annotated[
    OrganizationMembership, Depends(require_organization_role(Role.OWNER, Role.ADMIN))
]


@router.get("", response_model=list[ApprovalResponse])
def list_approvals(
    membership: CurrentMembership,
    db: Database,
    status: ApprovalStatus | None = None,
    risk_level: RiskLevel | None = None,
    team_run_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_approvals(
        db, membership.organization_id, status, risk_level, team_run_id, limit
    )


@router.get("/{approval_id}", response_model=ApprovalResponse)
def get_approval(approval_id: UUID, membership: CurrentMembership, db: Database):
    return service.get_approval(db, membership.organization_id, approval_id)


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
def approve(
    approval_id: UUID,
    data: ReviewRequest,
    membership: Reviewer,
    user: CurrentUser,
    db: Database,
    queue: JobQueueDep,
    request: Request,
):
    """Records the decision and queues the action; the worker executes it (M7)."""
    return service.review(
        db,
        membership.organization_id,
        approval_id,
        user.id,
        True,
        data.comment,
        request.app.state.settings,
        queue,
    )


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
def reject(
    approval_id: UUID,
    data: ReviewRequest,
    membership: Reviewer,
    user: CurrentUser,
    db: Database,
    queue: JobQueueDep,
    request: Request,
):
    """Rejection executes nothing, so it completes synchronously."""
    return service.review(
        db,
        membership.organization_id,
        approval_id,
        user.id,
        False,
        data.comment,
        request.app.state.settings,
        queue,
    )
