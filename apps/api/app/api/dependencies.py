from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.runtime import AgentRuntime
from app.agents.tools import ToolRegistry
from app.core.errors import APIError
from app.core.security import decode_access_token
from app.evaluation.runner import EvaluationRunner
from app.jobs import runtimes
from app.jobs.executor import JobExecutor
from app.jobs.queue import InlineQueue
from app.jobs.service import JobQueue
from app.mcp.client import McpClient
from app.mcp.urls import UrlPolicy
from app.models.identity import OrganizationMembership, RefreshSession, Role, User
from app.services.auth import utc
from app.services.health import check_readiness
from app.services.organizations import get_membership
from app.teams.runtime import TeamRuntime

bearer = HTTPBearer(auto_error=False)


def get_db(request: Request):
    with request.app.state.sessions() as session:
        yield session


Database = Annotated[Session, Depends(get_db)]


def get_current_user(
    request: Request,
    db: Database,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    denied = APIError(401, "unauthorized", "Authentication required.")
    if credentials is None:
        raise denied
    try:
        user_id, family_id = decode_access_token(
            credentials.credentials, request.app.state.settings
        )
    except jwt.InvalidTokenError as error:
        raise denied from error
    user = db.get(User, user_id)
    active = db.scalar(
        select(RefreshSession)
        .where(
            RefreshSession.user_id == user_id,
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),
        )
        .limit(1)
    )
    if not user or not user.is_active or not active or utc(active.expires_at) <= datetime.now(UTC):
        raise denied
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_membership(
    user: CurrentUser,
    db: Database,
    organization_id: Annotated[UUID, Header(alias="X-Organization-ID")],
) -> OrganizationMembership:
    return get_membership(db, user.id, organization_id)


CurrentMembership = Annotated[OrganizationMembership, Depends(get_current_membership)]


def require_organization_role(*roles: Role):
    def check(membership: CurrentMembership) -> OrganizationMembership:
        if membership.role not in roles:
            raise APIError(403, "forbidden", "Your organization role does not permit this action.")
        return membership

    return check


def require_browser_origin(request: Request):
    if request.headers.get("origin") not in request.app.state.settings.cors_origins:
        raise APIError(403, "untrusted_origin", "The request origin is not permitted.")


def get_mcp_url_policy(request: Request) -> UrlPolicy:
    return runtimes.mcp_url_policy(request.app.state.settings)


def get_mcp_client(request: Request) -> McpClient:
    return runtimes.mcp_client(request.app.state.settings)


McpUrls = Annotated[UrlPolicy, Depends(get_mcp_url_policy)]
Mcp = Annotated[McpClient, Depends(get_mcp_client)]


def get_internal_tools(request: Request) -> ToolRegistry:
    state = request.app.state
    return runtimes.internal_tools(
        lambda: check_readiness(state.engine, state.redis), state.sessions, state.settings
    )


InternalTools = Annotated[ToolRegistry, Depends(get_internal_tools)]


def get_agent_runtime(request: Request, mcp: Mcp, tools: InternalTools) -> AgentRuntime:
    state = request.app.state
    return runtimes.agent_runtime(state.settings, state.sessions, tools, mcp)


Runtime = Annotated[AgentRuntime, Depends(get_agent_runtime)]


def get_team_runtime(request: Request, mcp: Mcp, tools: InternalTools) -> TeamRuntime:
    state = request.app.state
    return runtimes.team_runtime(state.settings, state.sessions, tools, mcp)


TeamRunner = Annotated[TeamRuntime, Depends(get_team_runtime)]


def get_job_queue(request: Request, agents: Runtime, teams: TeamRunner) -> JobQueue:
    """Where new jobs go. Production: Redis, consumed by the worker service. Inline mode (tests
    only; refused in production) runs the same JobExecutor inside the request."""
    state = request.app.state
    if state.settings.execution_mode == "inline":
        executor = JobExecutor(
            state.sessions,
            state.settings,
            agents,
            teams,
            worker_id="inline",
            knowledge=runtimes.knowledge_ingestor(state.settings, state.sessions),
        )
        executor.evaluations = EvaluationRunner(state.sessions, state.settings, executor.run)
        executor.queue = InlineQueue(executor.run)
        return executor.queue
    return state.queue


JobQueueDep = Annotated[JobQueue, Depends(get_job_queue)]
