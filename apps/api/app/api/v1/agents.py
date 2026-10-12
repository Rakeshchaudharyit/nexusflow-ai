from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.dependencies import (
    CurrentMembership,
    CurrentUser,
    Database,
    InternalTools,
    JobQueueDep,
    require_organization_role,
)
from app.jobs import cancel as cancellation
from app.models.agents import AgentStatus
from app.models.identity import OrganizationMembership, Role
from app.schemas.agents import (
    AgentCreate,
    AgentResponse,
    AgentRunCreate,
    AgentRunDetail,
    AgentRunResult,
    AgentRunSummary,
    AgentUpdate,
)
from app.schemas.jobs import CancelResponse
from app.schemas.teams import AgentToolCreate, AgentToolResponse, AgentToolUpdate, ToolCatalogEntry
from app.services import agent_tools, agents

router = APIRouter(tags=["agents"])
AgentManager = Annotated[
    OrganizationMembership, Depends(require_organization_role(Role.OWNER, Role.ADMIN))
]


@router.post("/agents", response_model=AgentResponse, status_code=201)
def create_agent(data: AgentCreate, membership: AgentManager, user: CurrentUser, db: Database):
    return agents.create_agent(db, membership.organization_id, user, data)


@router.get("/agents", response_model=list[AgentResponse])
def list_agents(membership: CurrentMembership, db: Database, status: AgentStatus | None = None):
    return agents.list_agents(db, membership.organization_id, status)


@router.get("/agents/{agent_id}", response_model=AgentResponse)
def get_agent(agent_id: UUID, membership: CurrentMembership, db: Database):
    return agents.get_agent(db, membership.organization_id, agent_id)


@router.patch("/agents/{agent_id}", response_model=AgentResponse)
def update_agent(agent_id: UUID, data: AgentUpdate, membership: AgentManager, db: Database):
    return agents.update_agent(db, membership.organization_id, agent_id, data)


@router.post("/agents/{agent_id}/runs", response_model=AgentRunResult, status_code=201)
def run_agent(
    agent_id: UUID,
    data: AgentRunCreate,
    membership: CurrentMembership,
    user: CurrentUser,
    db: Database,
    queue: JobQueueDep,
    request: Request,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    return agents.run_agent(
        db,
        queue,
        request.app.state.settings,
        membership.organization_id,
        user,
        agent_id,
        data.input,
        data.thread_id,
    )


@router.get("/agent-runs", response_model=list[AgentRunSummary])
def list_runs(
    membership: CurrentMembership,
    db: Database,
    agent_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return agents.list_runs(db, membership.organization_id, agent_id, limit)


@router.get("/agent-runs/{run_id}", response_model=AgentRunDetail)
def get_run(run_id: UUID, membership: CurrentMembership, db: Database):
    return agents.get_run(db, membership.organization_id, run_id)


@router.post("/agent-runs/{run_id}/cancel", response_model=CancelResponse)
def cancel_run(run_id: UUID, membership: CurrentMembership, db: Database):
    """Queued runs stop immediately; running runs stop at their next graph stage."""
    return cancellation.cancel_agent_run(db, membership, run_id)


@router.get("/tools", response_model=list[ToolCatalogEntry])
def tool_catalog(membership: CurrentMembership, db: Database, internal: InternalTools):
    return agent_tools.tool_catalog(db, membership.organization_id, internal)


@router.get("/agents/{agent_id}/tools", response_model=list[AgentToolResponse])
def list_agent_tools(agent_id: UUID, membership: CurrentMembership, db: Database):
    return agent_tools.agent_tools(db, membership.organization_id, agent_id)


@router.post("/agents/{agent_id}/tools", response_model=AgentToolResponse, status_code=201)
def assign_tool(
    agent_id: UUID,
    data: AgentToolCreate,
    membership: AgentManager,
    db: Database,
    internal: InternalTools,
):
    return agent_tools.assign_tool(
        db, membership.organization_id, agent_id, data.tool_key, internal
    )


@router.patch("/agents/{agent_id}/tools/{assignment_id}", response_model=AgentToolResponse)
def update_tool_assignment(
    agent_id: UUID,
    assignment_id: UUID,
    data: AgentToolUpdate,
    membership: AgentManager,
    db: Database,
):
    return agent_tools.update_assignment(
        db, membership.organization_id, agent_id, assignment_id, data.is_enabled
    )


@router.delete("/agents/{agent_id}/tools/{assignment_id}", status_code=204)
def remove_tool_assignment(
    agent_id: UUID, assignment_id: UUID, membership: AgentManager, db: Database
):
    agent_tools.remove_assignment(db, membership.organization_id, agent_id, assignment_id)
    return Response(status_code=204)
