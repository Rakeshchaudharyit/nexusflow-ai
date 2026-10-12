from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.dependencies import CurrentMembership, Database
from app.models.observability import TraceRunType
from app.observability import service
from app.schemas.observability import ObservabilitySummary, TraceDetail, TraceSummary

router = APIRouter(tags=["observability"])
Origin = Literal["user", "evaluation", "all"]


@router.get("/traces", response_model=list[TraceSummary])
def list_traces(
    membership: CurrentMembership,
    db: Database,
    response: Response,
    run_type: TraceRunType | None = None,
    status: Annotated[str | None, Query(max_length=20)] = None,
    agent_id: UUID | None = None,
    team_id: UUID | None = None,
    run_id: UUID | None = None,
    error_code: Annotated[str | None, Query(max_length=80)] = None,
    error_category: Annotated[str | None, Query(max_length=20)] = None,
    origin: Origin = "user",
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
):
    response.headers["Cache-Control"] = "no-store"
    return service.list_traces(
        db,
        membership.organization_id,
        run_type=run_type,
        status=status,
        agent_id=agent_id,
        team_id=team_id,
        run_id=run_id,
        error_code=error_code,
        error_category=error_category,
        origin=origin,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/traces/{trace_id}", response_model=TraceDetail)
def get_trace(trace_id: UUID, membership: CurrentMembership, db: Database, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return service.get_trace(db, membership.organization_id, trace_id)


@router.get("/observability/summary", response_model=ObservabilitySummary)
def observability_summary(
    membership: CurrentMembership,
    db: Database,
    response: Response,
    hours: Annotated[int, Query(ge=1, le=720)] = 24,
    origin: Origin = "user",
):
    response.headers["Cache-Control"] = "no-store"
    return service.summary(db, membership.organization_id, hours, origin)
