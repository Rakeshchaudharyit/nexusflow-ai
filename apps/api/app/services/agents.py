import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import APIError
from app.jobs.service import LATEST_FIRST, JobQueue, create_job, deliver, latest_job
from app.memory.service import active_thread
from app.models.agents import Agent, AgentRun, AgentRunEvent, AgentStatus, RunStatus
from app.models.identity import User
from app.models.jobs import ExecutionJob, JobType
from app.observability.tracer import new_trace
from app.schemas.agents import (
    AgentCreate,
    AgentRunDetail,
    AgentRunEventResponse,
    AgentRunResult,
    AgentRunSummary,
    AgentUpdate,
    RunError,
    ToolCall,
)
from app.schemas.jobs import ExecutionInfo

STATUS_TRANSITIONS = {
    AgentStatus.DRAFT: {AgentStatus.ACTIVE, AgentStatus.ARCHIVED},
    AgentStatus.ACTIVE: {AgentStatus.DRAFT, AgentStatus.ARCHIVED},
    AgentStatus.ARCHIVED: {AgentStatus.DRAFT},
}


def slugify(name: str, fallback: str = "agent") -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:100] or fallback


def next_slug(db: Session, model, organization_id: UUID, base: str) -> str:
    """First free `base`, `base-2`, ... among an organization's rows of `model`."""
    taken = set(
        db.scalars(
            select(model.slug).where(
                model.organization_id == organization_id,
                (model.slug == base) | model.slug.startswith(base + "-"),
            )
        )
    )
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def create_agent(db: Session, organization_id: UUID, user: User, data: AgentCreate) -> Agent:
    base = slugify(data.name)
    for slug in (next_slug(db, Agent, organization_id, base), f"{base}-{uuid4().hex[:8]}"):
        agent = Agent(
            organization_id=organization_id,
            name=data.name,
            slug=slug,
            description=data.description,
            instructions=data.instructions,
            created_by_user_id=user.id,
        )
        db.add(agent)
        try:
            db.commit()
            return agent
        except IntegrityError:
            # A concurrent create claimed the slug; retry once with a random suffix.
            db.rollback()
    raise APIError(409, "agent_slug_conflict", "Could not allocate a unique agent slug.")


def list_agents(db: Session, organization_id: UUID, status: AgentStatus | None) -> list[Agent]:
    query = select(Agent).where(Agent.organization_id == organization_id)
    if status:
        query = query.where(Agent.status == status)
    return list(db.scalars(query.order_by(Agent.updated_at.desc(), Agent.id)))


def get_agent(db: Session, organization_id: UUID, agent_id: UUID) -> Agent:
    agent = db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id)
    )
    if agent is None:
        raise APIError(404, "agent_not_found", "Agent not found.")
    return agent


def update_agent(db: Session, organization_id: UUID, agent_id: UUID, data: AgentUpdate) -> Agent:
    agent = get_agent(db, organization_id, agent_id)
    changes = data.model_dump(exclude_unset=True)
    status = changes.pop("status", agent.status)
    if status != agent.status and status not in STATUS_TRANSITIONS[agent.status]:
        raise APIError(
            409,
            "invalid_status_transition",
            f"An agent cannot move from {agent.status.value} to {status.value}.",
        )
    if changes and AgentStatus.ARCHIVED in (agent.status, status):
        raise APIError(409, "agent_archived", "Restore the agent to draft before editing it.")
    for field, value in changes.items():
        setattr(agent, field, value)
    agent.status = status
    db.commit()
    return agent


def knowledge_retrieval(snapshot: dict | None) -> dict | None:
    """The knowledge_search call of a run, for display: never vectors or storage paths."""
    for record in (snapshot or {}).get("tool_results", []):
        if record.get("tool") == "knowledge_search":
            output = record.get("output") or {}
            return {
                key: output.get(key)
                for key in ("query", "sources_searched", "results", "candidates", "insufficient")
            }
    return None


def tool_calls(snapshot: dict | None) -> list[ToolCall]:
    snapshot = snapshot or {}
    calls = [
        ToolCall(
            tool_key=record.get("tool_key", record["tool"]),
            tool_type=record.get("tool_type", "internal"),
            tool=record["tool"],
            status="completed",
            server_id=record.get("metadata", {}).get("server_id"),
            server_name=record.get("metadata", {}).get("server_name"),
            duration_ms=record.get("metadata", {}).get("duration_ms"),
        )
        for record in snapshot.get("tool_results", [])
    ]
    for error in snapshot.get("errors", []):
        details = error.get("details") or {}
        if details.get("tool_key") or details.get("tool_name"):
            calls.append(
                ToolCall(
                    tool_key=details.get("tool_key", details.get("tool_name")),
                    tool_type=details.get("tool_type", "internal"),
                    tool=details.get("tool_name", details.get("tool_key")),
                    status="failed",
                    server_id=details.get("server_id"),
                    server_name=details.get("server_name"),
                )
            )
    return calls


def execution_status_column():
    """Latest job status for each run, as a correlated subquery (one job per agent run)."""
    return (
        select(ExecutionJob.status)
        .where(
            ExecutionJob.agent_run_id == AgentRun.id,
            ExecutionJob.organization_id == AgentRun.organization_id,
        )
        .order_by(*LATEST_FIRST)
        .limit(1)
        .scalar_subquery()
    )


def run_result(run: AgentRun, job: ExecutionJob | None = None) -> AgentRunResult:
    output = run.final_output or {}
    intent = output.get("intent") or (run.state_snapshot or {}).get("intent")
    return AgentRunResult(
        run_id=run.id,
        agent_id=run.agent_id,
        status=run.status,
        intent=intent,
        summary=output.get("summary"),
        tools_used=output.get("tools_used", []),
        tool_calls=tool_calls(run.state_snapshot),
        duration_ms=run.duration_ms,
        step_count=run.step_count,
        error=RunError(code=run.error_code, message=run.error_message) if run.error_code else None,
        created_at=run.created_at,
        execution=ExecutionInfo.of(job),
        thread_id=run.thread_id,
    )


def run_agent(
    db: Session,
    queue: JobQueue,
    settings: Settings,
    organization_id: UUID,
    user: User,
    agent_id: UUID,
    input_text: str,
    thread_id: UUID | None = None,
    evaluation_run_id: UUID | None = None,
) -> AgentRunResult:
    """Persist the run and its job, commit, hand the job id to the queue, and return at once.
    The graph runs in the worker (M7); the client polls the run for its outcome."""
    agent = get_agent(db, organization_id, agent_id)
    if agent.status != AgentStatus.ACTIVE:
        raise APIError(409, "agent_not_active", "Activate the agent before running it.")
    run = AgentRun(
        organization_id=organization_id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        status=RunStatus.QUEUED,
        input_text=input_text,
        thread_id=active_thread(db, organization_id, thread_id, evaluation_run_id) and thread_id,
        evaluation_run_id=evaluation_run_id,
    )
    db.add(run)
    db.flush()
    # M10: one trace per run, committed with it (spans are added by the worker).
    db.add(
        new_trace(
            organization_id,
            agent_run_id=run.id,
            agent_id=agent.id,
            thread_id=run.thread_id,
            evaluation_run_id=evaluation_run_id,
        )
    )
    job = create_job(
        db,
        settings,
        organization_id=organization_id,
        job_type=JobType.SINGLE_AGENT_RUN,
        agent_run_id=run.id,
    )
    db.commit()
    deliver(db, queue, job.id)
    db.refresh(run)
    db.refresh(job)
    return run_result(run, job)


def summary_query(organization_id: UUID):
    return (
        select(AgentRun, Agent.name, execution_status_column())
        .join(
            Agent,
            (Agent.id == AgentRun.agent_id) & (Agent.organization_id == AgentRun.organization_id),
        )
        .where(AgentRun.organization_id == organization_id)
    )


def run_summary(run: AgentRun, agent_name: str, execution_status=None) -> dict:
    return {
        "id": run.id,
        "agent_id": run.agent_id,
        "agent_name": agent_name,
        "status": run.status,
        "input_text": run.input_text,
        "created_at": run.created_at,
        "created_by_user_id": run.created_by_user_id,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "duration_ms": run.duration_ms,
        "step_count": run.step_count,
        "execution_status": execution_status,
        "thread_id": run.thread_id,
    }


def list_runs(
    db: Session, organization_id: UUID, agent_id: UUID | None, limit: int
) -> list[AgentRunSummary]:
    # Runs executed by evaluations (M10) are listed under their evaluation, not here.
    query = summary_query(organization_id).where(AgentRun.evaluation_run_id.is_(None))
    if agent_id:
        query = query.where(AgentRun.agent_id == agent_id)
    rows = db.execute(query.order_by(AgentRun.created_at.desc(), AgentRun.id).limit(limit))
    return [AgentRunSummary(**run_summary(*row)) for row in rows]


def get_run(db: Session, organization_id: UUID, run_id: UUID) -> AgentRunDetail:
    row = db.execute(summary_query(organization_id).where(AgentRun.id == run_id)).first()
    if row is None:
        raise APIError(404, "run_not_found", "Run not found.")
    run, agent_name, execution_status = row
    events = db.scalars(
        select(AgentRunEvent)
        .where(
            AgentRunEvent.run_id == run.id,
            AgentRunEvent.organization_id == organization_id,
        )
        .order_by(AgentRunEvent.sequence)
    )
    job = latest_job(db, organization_id, agent_run_id=run.id)
    return AgentRunDetail(
        **run_summary(run, agent_name, execution_status),
        execution=ExecutionInfo.of(job),
        final_output=run.final_output,
        state=run.state_snapshot,
        error=RunError(code=run.error_code, message=run.error_message) if run.error_code else None,
        tool_calls=tool_calls(run.state_snapshot),
        events=[AgentRunEventResponse.model_validate(event) for event in events],
        memory_context=run.memory_context,
        knowledge=knowledge_retrieval(run.state_snapshot),
    )
