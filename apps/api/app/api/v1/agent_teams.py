from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import (
    CurrentMembership,
    CurrentUser,
    Database,
    JobQueueDep,
    require_organization_role,
)
from app.jobs import cancel as cancellation
from app.models.agents import RunStatus
from app.models.identity import OrganizationMembership, Role
from app.schemas.jobs import CancelResponse
from app.schemas.teams import (
    TeamCreate,
    TeamDetail,
    TeamMemberInput,
    TeamMemberUpdate,
    TeamResponse,
    TeamRunCreate,
    TeamRunDetail,
    TeamRunResult,
    TeamRunSummary,
    TeamUpdate,
)
from app.services import agent_teams as service

router = APIRouter(tags=["agent teams"])
Manager = Annotated[
    OrganizationMembership, Depends(require_organization_role(Role.OWNER, Role.ADMIN))
]


@router.post("/agent-teams", response_model=TeamDetail, status_code=201)
def create_team(data: TeamCreate, membership: Manager, user: CurrentUser, db: Database):
    return service.create_team(db, membership.organization_id, user, data)


@router.get("/agent-teams", response_model=list[TeamResponse])
def list_teams(membership: CurrentMembership, db: Database):
    return service.list_teams(db, membership.organization_id)


@router.get("/agent-teams/{team_id}", response_model=TeamDetail)
def get_team(team_id: UUID, membership: CurrentMembership, db: Database):
    return service.team_detail(db, service.get_team(db, membership.organization_id, team_id))


@router.patch("/agent-teams/{team_id}", response_model=TeamDetail)
def update_team(team_id: UUID, data: TeamUpdate, membership: Manager, db: Database):
    return service.update_team(db, membership.organization_id, team_id, data)


@router.post("/agent-teams/{team_id}/members", response_model=TeamDetail, status_code=201)
def add_member(team_id: UUID, data: TeamMemberInput, membership: Manager, db: Database):
    return service.add_member(db, membership.organization_id, team_id, data)


@router.patch("/agent-teams/{team_id}/members/{member_id}", response_model=TeamDetail)
def update_member(
    team_id: UUID, member_id: UUID, data: TeamMemberUpdate, membership: Manager, db: Database
):
    return service.update_member(db, membership.organization_id, team_id, member_id, data)


@router.delete("/agent-teams/{team_id}/members/{member_id}", response_model=TeamDetail)
def remove_member(team_id: UUID, member_id: UUID, membership: Manager, db: Database):
    return service.remove_member(db, membership.organization_id, team_id, member_id)


@router.post("/agent-teams/{team_id}/runs", response_model=TeamRunResult, status_code=201)
def run_team(
    team_id: UUID,
    data: TeamRunCreate,
    membership: CurrentMembership,
    user: CurrentUser,
    db: Database,
    queue: JobQueueDep,
    request: Request,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    return service.run_team(
        db,
        queue,
        request.app.state.settings,
        membership.organization_id,
        user,
        team_id,
        data.objective,
        data.thread_id,
    )


@router.get("/agent-team-runs", response_model=list[TeamRunSummary])
def list_team_runs(
    membership: CurrentMembership,
    db: Database,
    team_id: UUID | None = None,
    status: RunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_team_runs(db, membership.organization_id, team_id, status, limit)


@router.get("/agent-team-runs/{run_id}", response_model=TeamRunDetail)
def get_team_run(run_id: UUID, membership: CurrentMembership, db: Database):
    return service.get_team_run(db, membership.organization_id, run_id)


@router.post("/agent-team-runs/{run_id}/cancel", response_model=CancelResponse)
def cancel_team_run(run_id: UUID, membership: CurrentMembership, db: Database):
    """Also closes a pending approval, so approving afterwards executes nothing."""
    return cancellation.cancel_team_run(db, membership, run_id)
