"""Tenant-scoped agent teams, membership and team runs."""

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import APIError
from app.jobs.service import LATEST_FIRST, JobQueue, create_job, deliver, latest_job
from app.memory.service import active_thread
from app.models.agents import Agent, AgentRunEvent, AgentStatus, RunEventType, RunStatus
from app.models.identity import User
from app.models.jobs import ExecutionJob, JobType
from app.models.knowledge import AgentKnowledgeSource, KnowledgeSource
from app.models.teams import AgentTeam, AgentTeamMember, AgentTeamRun, TeamStatus
from app.observability.tracer import new_trace
from app.schemas.agents import AgentRunEventResponse, RunError
from app.schemas.jobs import ExecutionInfo
from app.schemas.teams import (
    AgentStepResult,
    Handoff,
    MemberKnowledge,
    TeamCreate,
    TeamDetail,
    TeamMemberInput,
    TeamMemberResponse,
    TeamMemberUpdate,
    TeamResponse,
    TeamRunDetail,
    TeamRunResult,
    TeamRunSummary,
    TeamUpdate,
)
from app.services.agent_tools import assignment_response, list_assignments
from app.services.agents import next_slug, slugify
from app.services.approvals import run_action
from app.teams.config import team_problems

STATUS_TRANSITIONS = {
    TeamStatus.DRAFT: {TeamStatus.ACTIVE, TeamStatus.ARCHIVED},
    TeamStatus.ACTIVE: {TeamStatus.DRAFT, TeamStatus.ARCHIVED},
    TeamStatus.ARCHIVED: {TeamStatus.DRAFT},
}

AGENT_STEP_EVENTS = (
    RunEventType.HANDOFF_STARTED,
    RunEventType.AGENT_COMPLETED,
    RunEventType.AGENT_FAILED,
)


def get_team(db: Session, organization_id: UUID, team_id: UUID) -> AgentTeam:
    team = db.scalar(
        select(AgentTeam).where(
            AgentTeam.id == team_id, AgentTeam.organization_id == organization_id
        )
    )
    if team is None:
        raise APIError(404, "team_not_found", "Team not found.")
    return team


def member_rows(db: Session, team: AgentTeam) -> list[tuple[AgentTeamMember, Agent]]:
    return list(
        db.execute(
            select(AgentTeamMember, Agent)
            .join(
                Agent,
                (Agent.id == AgentTeamMember.agent_id)
                & (Agent.organization_id == AgentTeamMember.organization_id),
            )
            .where(
                AgentTeamMember.team_id == team.id,
                AgentTeamMember.organization_id == team.organization_id,
            )
            .order_by(AgentTeamMember.position, AgentTeamMember.role)
        )
    )


def problems_for(rows: list[tuple[AgentTeamMember, Agent]]) -> list[str]:
    return team_problems(
        [member.role for member, _ in rows],
        [agent.name for _, agent in rows if agent.status != AgentStatus.ACTIVE],
    )


def team_response(team: AgentTeam, member_count: int) -> TeamResponse:
    return TeamResponse(
        id=team.id,
        organization_id=team.organization_id,
        name=team.name,
        slug=team.slug,
        description=team.description,
        status=team.status,
        workspace_memory_enabled=team.workspace_memory_enabled,
        member_count=member_count,
        created_by_user_id=team.created_by_user_id,
        created_at=team.created_at,
        updated_at=team.updated_at,
    )


def team_detail(db: Session, team: AgentTeam) -> TeamDetail:
    rows = member_rows(db, team)
    assignments: dict[UUID, list] = {}
    for item in list_assignments(db, team.organization_id, [agent.id for _, agent in rows]):
        assignments.setdefault(item.agent_id, []).append(assignment_response(item))
    knowledge: dict[UUID, list[MemberKnowledge]] = {}
    for grant, source in db.execute(
        select(AgentKnowledgeSource, KnowledgeSource)
        .join(
            KnowledgeSource,
            (KnowledgeSource.id == AgentKnowledgeSource.source_id)
            & (KnowledgeSource.organization_id == AgentKnowledgeSource.organization_id),
        )
        .where(
            AgentKnowledgeSource.organization_id == team.organization_id,
            AgentKnowledgeSource.agent_id.in_([agent.id for _, agent in rows]),
        )
        .order_by(KnowledgeSource.name)
    ):
        knowledge.setdefault(grant.agent_id, []).append(
            MemberKnowledge(
                source_id=source.id,
                source_name=source.name,
                source_status=source.status.value,
                is_enabled=grant.is_enabled,
            )
        )
    return TeamDetail(
        **team_response(team, len(rows)).model_dump(),
        members=[
            TeamMemberResponse(
                id=member.id,
                agent_id=agent.id,
                agent_name=agent.name,
                agent_status=agent.status,
                role=member.role,
                position=member.position,
                is_required=member.is_required,
                tools=assignments.get(agent.id, []),
                knowledge_sources=knowledge.get(agent.id, []),
            )
            for member, agent in rows
        ],
        problems=problems_for(rows),
    )


def require_agent(db: Session, organization_id: UUID, agent_id: UUID) -> Agent:
    agent = db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id)
    )
    if agent is None:
        raise APIError(422, "agent_not_found", "Team members must be agents in this workspace.")
    return agent


def save_members(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise APIError(
            409, "team_member_conflict", "Each role and each agent can appear once per team."
        ) from error


def create_team(db: Session, organization_id: UUID, user: User, data: TeamCreate) -> TeamDetail:
    for member in data.members:
        require_agent(db, organization_id, member.agent_id)
    base = slugify(data.name, "team")
    team = AgentTeam(
        id=uuid4(),
        organization_id=organization_id,
        name=data.name,
        slug=next_slug(db, AgentTeam, organization_id, base),
        description=data.description,
        created_by_user_id=user.id,
    )
    db.add(team)
    db.flush()
    for member in data.members:
        db.add(member_row(team, member))
    save_members(db)
    return team_detail(db, team)


def member_row(team: AgentTeam, member: TeamMemberInput) -> AgentTeamMember:
    return AgentTeamMember(
        organization_id=team.organization_id,
        team_id=team.id,
        agent_id=member.agent_id,
        role=member.role,
        position=member.position,
        is_required=member.is_required,
    )


def list_teams(db: Session, organization_id: UUID) -> list[TeamResponse]:
    counts = {
        team_id: count
        for team_id, count in db.execute(
            select(AgentTeamMember.team_id, func.count())
            .where(AgentTeamMember.organization_id == organization_id)
            .group_by(AgentTeamMember.team_id)
        )
    }
    teams = db.scalars(
        select(AgentTeam)
        .where(AgentTeam.organization_id == organization_id)
        .order_by(AgentTeam.updated_at.desc(), AgentTeam.id)
    )
    return [team_response(team, counts.get(team.id, 0)) for team in teams]


def ensure_runnable(db: Session, team: AgentTeam) -> None:
    problems = problems_for(member_rows(db, team))
    if problems:
        raise APIError(
            409, "team_invalid", "The team cannot be active: " + "; ".join(problems) + "."
        )


def update_team(db: Session, organization_id: UUID, team_id: UUID, data: TeamUpdate) -> TeamDetail:
    team = get_team(db, organization_id, team_id)
    changes = data.model_dump(exclude_unset=True)
    status = changes.pop("status", team.status)
    if status != team.status and status not in STATUS_TRANSITIONS[team.status]:
        raise APIError(
            409,
            "invalid_status_transition",
            f"A team cannot move from {team.status.value} to {status.value}.",
        )
    if changes and TeamStatus.ARCHIVED in (team.status, status):
        raise APIError(409, "team_archived", "Restore the team to draft before editing it.")
    if status == TeamStatus.ACTIVE:
        ensure_runnable(db, team)
    for field, value in changes.items():
        setattr(team, field, value)
    team.status = status
    db.commit()
    return team_detail(db, team)


def editable_team(db: Session, organization_id: UUID, team_id: UUID) -> AgentTeam:
    team = get_team(db, organization_id, team_id)
    if team.status == TeamStatus.ARCHIVED:
        raise APIError(409, "team_archived", "Restore the team to draft before editing it.")
    return team


def finish_member_change(db: Session, team: AgentTeam) -> TeamDetail:
    db.flush()
    if team.status == TeamStatus.ACTIVE:
        problems = problems_for(member_rows(db, team))
        if problems:
            db.rollback()
            raise APIError(
                409,
                "team_invalid",
                "This change would leave the active team invalid: " + "; ".join(problems) + ".",
            )
    save_members(db)
    return team_detail(db, team)


def add_member(
    db: Session, organization_id: UUID, team_id: UUID, data: TeamMemberInput
) -> TeamDetail:
    team = editable_team(db, organization_id, team_id)
    require_agent(db, organization_id, data.agent_id)
    db.add(member_row(team, data))
    try:
        return finish_member_change(db, team)
    except IntegrityError as error:
        db.rollback()
        raise APIError(
            409, "team_member_conflict", "Each role and each agent can appear once per team."
        ) from error


def get_member(db: Session, team: AgentTeam, member_id: UUID) -> AgentTeamMember:
    member = db.scalar(
        select(AgentTeamMember).where(
            AgentTeamMember.id == member_id,
            AgentTeamMember.team_id == team.id,
            AgentTeamMember.organization_id == team.organization_id,
        )
    )
    if member is None:
        raise APIError(404, "team_member_not_found", "Team member not found.")
    return member


def update_member(
    db: Session, organization_id: UUID, team_id: UUID, member_id: UUID, data: TeamMemberUpdate
) -> TeamDetail:
    team = editable_team(db, organization_id, team_id)
    member = get_member(db, team, member_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)
    try:
        return finish_member_change(db, team)
    except IntegrityError as error:
        db.rollback()
        raise APIError(
            409, "team_member_conflict", "Each role and each agent can appear once per team."
        ) from error


def remove_member(db: Session, organization_id: UUID, team_id: UUID, member_id: UUID) -> TeamDetail:
    team = editable_team(db, organization_id, team_id)
    db.delete(get_member(db, team, member_id))
    return finish_member_change(db, team)


def execution_status_column():
    """Status of the run's latest job (team run, then approval action), as a subquery."""
    return (
        select(ExecutionJob.status)
        .where(
            ExecutionJob.team_run_id == AgentTeamRun.id,
            ExecutionJob.organization_id == AgentTeamRun.organization_id,
        )
        .order_by(*LATEST_FIRST)
        .limit(1)
        .scalar_subquery()
    )


def run_result(run: AgentTeamRun, job: ExecutionJob | None = None) -> TeamRunResult:
    snapshot = run.state_snapshot or {}
    return TeamRunResult(
        run_id=run.id,
        team_id=run.team_id,
        status=run.status,
        final_output=run.final_output,
        agents_executed=snapshot.get("completed_agents", []),
        duration_ms=run.duration_ms,
        step_count=run.step_count,
        error=RunError(code=run.error_code, message=run.error_message) if run.error_code else None,
        action=(run.final_output or {}).get("action"),
        created_at=run.created_at,
        execution=ExecutionInfo.of(job),
        thread_id=run.thread_id,
    )


def run_team(
    db: Session,
    queue: JobQueue,
    settings: Settings,
    organization_id: UUID,
    user: User,
    team_id: UUID,
    objective: str,
    thread_id: UUID | None = None,
    evaluation_run_id: UUID | None = None,
) -> TeamRunResult:
    """Persist the team run and its job, commit, enqueue, and return without orchestrating."""
    team = get_team(db, organization_id, team_id)
    if team.status != TeamStatus.ACTIVE:
        raise APIError(409, "team_not_active", "Activate the team before running it.")
    run = AgentTeamRun(
        organization_id=organization_id,
        team_id=team.id,
        created_by_user_id=user.id,
        status=RunStatus.QUEUED,
        objective=objective,
        thread_id=active_thread(db, organization_id, thread_id, evaluation_run_id) and thread_id,
        evaluation_run_id=evaluation_run_id,
    )
    db.add(run)
    db.flush()
    # M10: one trace per run, committed with it (spans are added by the worker).
    db.add(
        new_trace(
            organization_id,
            team_run_id=run.id,
            team_id=team.id,
            thread_id=run.thread_id,
            evaluation_run_id=evaluation_run_id,
        )
    )
    job = create_job(
        db,
        settings,
        organization_id=organization_id,
        job_type=JobType.TEAM_RUN,
        team_run_id=run.id,
    )
    db.commit()
    deliver(db, queue, job.id)
    db.refresh(run)
    db.refresh(job)
    return run_result(run, job)


def summary_query(organization_id: UUID):
    return (
        select(AgentTeamRun, AgentTeam.name, execution_status_column())
        .join(
            AgentTeam,
            (AgentTeam.id == AgentTeamRun.team_id)
            & (AgentTeam.organization_id == AgentTeamRun.organization_id),
        )
        .where(AgentTeamRun.organization_id == organization_id)
    )


def summary_fields(run: AgentTeamRun, team_name: str, execution_status=None) -> dict:
    return {
        "id": run.id,
        "team_id": run.team_id,
        "team_name": team_name,
        "status": run.status,
        "objective": run.objective,
        "created_at": run.created_at,
        "created_by_user_id": run.created_by_user_id,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "duration_ms": run.duration_ms,
        "step_count": run.step_count,
        "execution_status": execution_status,
        "thread_id": run.thread_id,
    }


def list_team_runs(
    db: Session,
    organization_id: UUID,
    team_id: UUID | None,
    status: RunStatus | None,
    limit: int,
) -> list[TeamRunSummary]:
    # Runs executed by evaluations (M10) are listed under their evaluation, not here.
    query = summary_query(organization_id).where(AgentTeamRun.evaluation_run_id.is_(None))
    if team_id:
        query = query.where(AgentTeamRun.team_id == team_id)
    if status:
        query = query.where(AgentTeamRun.status == status)
    rows = db.execute(query.order_by(AgentTeamRun.created_at.desc(), AgentTeamRun.id).limit(limit))
    return [TeamRunSummary(**summary_fields(*row)) for row in rows]


def step_results(events: list[AgentRunEvent], names: dict[str, str]) -> list[AgentStepResult]:
    results = []
    for event in events:
        if event.event_type == RunEventType.AGENT_COMPLETED:
            payload = event.output_payload or {}
            results.append(
                AgentStepResult(
                    agent_id=event.agent_id,
                    agent_name=names.get(str(event.agent_id)),
                    role=event.agent_role,
                    status="completed",
                    output=payload.get("output"),
                    tool_calls=payload.get("tool_calls", []),
                    duration_ms=event.duration_ms,
                    error=None,
                )
            )
        elif event.event_type == RunEventType.AGENT_FAILED:
            payload = event.output_payload or {}
            results.append(
                AgentStepResult(
                    agent_id=event.agent_id,
                    agent_name=names.get(str(event.agent_id)),
                    role=event.agent_role,
                    status="failed",
                    output=None,
                    tool_calls=[
                        {key: payload[key] for key in payload if key.startswith(("tool", "server"))}
                    ]
                    if payload.get("tool_key")
                    else [],
                    duration_ms=event.duration_ms,
                    error=RunError(
                        code=payload.get("error_code", "internal_error"),
                        message=event.error_message or "",
                    ),
                )
            )
    return results


def get_team_run(db: Session, organization_id: UUID, run_id: UUID) -> TeamRunDetail:
    row = db.execute(summary_query(organization_id).where(AgentTeamRun.id == run_id)).first()
    if row is None:
        raise APIError(404, "team_run_not_found", "Team run not found.")
    run, team_name, execution_status = row
    events = list(
        db.scalars(
            select(AgentRunEvent)
            .where(
                AgentRunEvent.team_run_id == run.id,
                AgentRunEvent.organization_id == organization_id,
            )
            .order_by(AgentRunEvent.sequence)
        )
    )
    # The timeline keeps every attempt; results and handoffs describe the latest one only.
    agent_events = [event for event in events if event.event_type in AGENT_STEP_EVENTS]
    latest = max((event.attempt or 0 for event in agent_events), default=0)
    current = [event for event in agent_events if (event.attempt or 0) == latest]
    snapshot = run.state_snapshot or {}
    plan = snapshot.get("plan", [])
    names = {step["agent_id"]: step["agent_name"] for step in plan}
    handoffs = [
        Handoff(
            sequence=event.sequence,
            to_role=event.agent_role,
            agent_name=(event.input_payload or {}).get("agent_name"),
            task=(event.input_payload or {}).get("task", ""),
            context=(event.input_payload or {}).get("context", {}),
        )
        for event in current
        if event.event_type == RunEventType.HANDOFF_STARTED
    ]
    return TeamRunDetail(
        **summary_fields(run, team_name, execution_status),
        plan=plan,
        final_output=run.final_output,
        validation=snapshot.get("validation_result"),
        revisions=snapshot.get("revisions", 0),
        results=step_results(current, names),
        handoffs=handoffs,
        error=RunError(code=run.error_code, message=run.error_message) if run.error_code else None,
        action=(run.final_output or {}).get("action"),
        approval=run_action(db, organization_id, run.id),
        events=[AgentRunEventResponse.model_validate(event) for event in events],
        execution=ExecutionInfo.of(latest_job(db, organization_id, team_run_id=run.id)),
        memory_context=run.memory_context,
    )
