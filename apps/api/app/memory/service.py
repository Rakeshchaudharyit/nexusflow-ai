"""Threads and memory API logic. Every query is organization-scoped; composite foreign keys
back that up in the database. Roles:

- threads: any member may create, list and read; rename/archive needs owner/admin or creator
- memory create: thread scope for any member; agent and workspace scope need owner/admin,
  because they change what other runs receive
- update/delete: owner/admin, or the member who created a manual entry
- delete: manual entries are hard-deleted; run-derived entries are deactivated, keeping the
  provenance of what earlier runs may have used
"""

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.memory.context import clean
from app.models.agents import Agent, AgentRun
from app.models.identity import OrganizationMembership, Role
from app.models.memory import (
    MemoryEntry,
    MemoryScope,
    MemorySource,
    MemoryThread,
    MemoryType,
    ThreadStatus,
)
from app.models.teams import AgentTeam, AgentTeamRun
from app.schemas.memory import (
    MemoryCreate,
    MemoryDeleted,
    MemoryResponse,
    MemoryUpdate,
    ThreadCreate,
    ThreadDetail,
    ThreadFact,
    ThreadResponse,
    ThreadRun,
    ThreadUpdate,
)

MANAGERS = (Role.OWNER, Role.ADMIN)
DETAIL_MEMORY_LIMIT = 50
DETAIL_RUN_LIMIT = 10
# Memory is reusable context; credentials never belong in it.
SECRET = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|bearer\s+\S+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bsk-[a-z0-9]{16,})"
)


def now() -> datetime:
    return datetime.now(UTC)


def aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def manager(membership: OrganizationMembership) -> bool:
    return membership.role in MANAGERS


def reject_secrets(*texts: str | None) -> None:
    if any(text and SECRET.search(text) for text in texts):
        raise APIError(
            422, "memory_secret_rejected", "Memory must not contain passwords, keys or tokens."
        )


# --- threads ----------------------------------------------------------------------------------


def get_thread(
    db: Session, organization_id: UUID, thread_id: UUID, evaluation_run_id: UUID | None = None
) -> MemoryThread:
    """A user thread, or (for the evaluation runner) that evaluation run's own thread.
    Evaluation threads are invisible to users, and user threads to evaluations."""
    thread = db.scalar(
        select(MemoryThread).where(
            MemoryThread.id == thread_id, MemoryThread.organization_id == organization_id
        )
    )
    if thread is None or thread.evaluation_run_id != evaluation_run_id:
        raise APIError(404, "thread_not_found", "Thread not found.")
    return thread


def active_thread(
    db: Session,
    organization_id: UUID,
    thread_id: UUID | None,
    evaluation_run_id: UUID | None = None,
):
    """Validate a run's optional thread: same organization and not archived."""
    if thread_id is None:
        return None
    thread = get_thread(db, organization_id, thread_id, evaluation_run_id)
    if thread.status != ThreadStatus.ACTIVE:
        raise APIError(409, "thread_archived", "The thread is archived.")
    thread.last_activity_at = now()
    return thread


def thread_counts(db: Session, organization_id: UUID, thread_ids: list[UUID]) -> dict:
    def grouped(model, column):
        return dict(
            db.execute(
                select(column, func.count())
                .where(model.organization_id == organization_id, column.in_(thread_ids))
                .group_by(column)
            ).all()
        )

    return {
        "agent": grouped(AgentRun, AgentRun.thread_id),
        "team": grouped(AgentTeamRun, AgentTeamRun.thread_id),
        "memory": dict(
            db.execute(
                select(MemoryEntry.thread_id, func.count())
                .where(
                    MemoryEntry.organization_id == organization_id,
                    MemoryEntry.thread_id.in_(thread_ids),
                    MemoryEntry.is_active.is_(True),
                )
                .group_by(MemoryEntry.thread_id)
            ).all()
        ),
    }


def thread_response(thread: MemoryThread, counts: dict) -> ThreadResponse:
    return ThreadResponse(
        id=thread.id,
        organization_id=thread.organization_id,
        created_by_user_id=thread.created_by_user_id,
        title=thread.title,
        status=thread.status,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        last_activity_at=thread.last_activity_at,
        agent_run_count=counts["agent"].get(thread.id, 0),
        team_run_count=counts["team"].get(thread.id, 0),
        memory_count=counts["memory"].get(thread.id, 0),
    )


def create_thread(
    db: Session, membership: OrganizationMembership, data: ThreadCreate
) -> ThreadResponse:
    thread = MemoryThread(
        organization_id=membership.organization_id,
        created_by_user_id=membership.user_id,
        title=clean(data.title, 200),
        last_activity_at=now(),
    )
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread_response(thread, {"agent": {}, "team": {}, "memory": {}})


def list_threads(
    db: Session, organization_id: UUID, status: ThreadStatus | None, limit: int
) -> list[ThreadResponse]:
    query = select(MemoryThread).where(
        MemoryThread.organization_id == organization_id,
        MemoryThread.evaluation_run_id.is_(None),
    )
    if status is not None:
        query = query.where(MemoryThread.status == status)
    threads = list(
        db.scalars(
            query.order_by(MemoryThread.last_activity_at.desc(), MemoryThread.id).limit(limit)
        )
    )
    counts = thread_counts(db, organization_id, [thread.id for thread in threads])
    return [thread_response(thread, counts) for thread in threads]


def update_thread(
    db: Session, membership: OrganizationMembership, thread_id: UUID, data: ThreadUpdate
) -> ThreadResponse:
    thread = get_thread(db, membership.organization_id, thread_id)
    if not manager(membership) and thread.created_by_user_id != membership.user_id:
        raise APIError(403, "forbidden", "Only the creator or an admin can change this thread.")
    if data.title is not None:
        thread.title = clean(data.title, 200)
    if data.status is not None:
        thread.status = data.status
    db.commit()
    db.refresh(thread)
    return thread_response(thread, thread_counts(db, membership.organization_id, [thread.id]))


def get_thread_detail(db: Session, organization_id: UUID, thread_id: UUID) -> ThreadDetail:
    """Bounded: at most DETAIL_MEMORY_LIMIT entries and DETAIL_RUN_LIMIT recent runs."""
    thread = get_thread(db, organization_id, thread_id)
    entries = list(
        db.scalars(
            select(MemoryEntry)
            .where(
                MemoryEntry.organization_id == organization_id,
                MemoryEntry.thread_id == thread.id,
            )
            .order_by(
                MemoryEntry.is_active.desc(),
                MemoryEntry.importance.desc(),
                MemoryEntry.updated_at.desc(),
            )
            .limit(DETAIL_MEMORY_LIMIT)
        )
    )
    active = [entry for entry in entries if entry.is_active]
    summary = next((e.content for e in active if e.memory_type == MemoryType.SUMMARY), None)
    facts = [
        ThreadFact(
            id=e.id,
            key=e.fact_key,
            value=e.fact_value,
            confidence=e.confidence,
            source_type=e.source_type,
            updated_at=e.updated_at,
        )
        for e in sorted((e for e in active if e.fact_key), key=lambda e: e.fact_key)
    ]
    agent_runs = db.execute(
        select(AgentRun.id, AgentRun.status, Agent.name, AgentRun.created_at)
        .join(
            Agent,
            (Agent.id == AgentRun.agent_id) & (Agent.organization_id == AgentRun.organization_id),
        )
        .where(AgentRun.organization_id == organization_id, AgentRun.thread_id == thread.id)
        .order_by(AgentRun.created_at.desc())
        .limit(DETAIL_RUN_LIMIT)
    ).all()
    team_runs = db.execute(
        select(AgentTeamRun.id, AgentTeamRun.status, AgentTeam.name, AgentTeamRun.created_at)
        .join(
            AgentTeam,
            (AgentTeam.id == AgentTeamRun.team_id)
            & (AgentTeam.organization_id == AgentTeamRun.organization_id),
        )
        .where(AgentTeamRun.organization_id == organization_id, AgentTeamRun.thread_id == thread.id)
        .order_by(AgentTeamRun.created_at.desc())
        .limit(DETAIL_RUN_LIMIT)
    ).all()
    runs = [
        ThreadRun(kind="agent", id=r[0], status=r[1], label=r[2], created_at=r[3])
        for r in agent_runs
    ]
    runs += [
        ThreadRun(kind="team", id=r[0], status=r[1], label=r[2], created_at=r[3]) for r in team_runs
    ]
    runs.sort(key=lambda run: aware(run.created_at), reverse=True)
    base = thread_response(thread, thread_counts(db, organization_id, [thread.id]))
    return ThreadDetail(
        **base.model_dump(),
        summary=summary,
        facts=facts,
        memory=[memory_response(entry) for entry in entries],
        recent_runs=runs[:DETAIL_RUN_LIMIT],
    )


# --- memory -----------------------------------------------------------------------------------


def memory_response(
    entry: MemoryEntry, thread_title: str | None = None, agent_name: str | None = None
) -> MemoryResponse:
    expires = aware(entry.expires_at)
    response = MemoryResponse.model_validate(entry)
    response.in_context = entry.is_active and (expires is None or expires > now())
    response.thread_title = thread_title
    response.agent_name = agent_name
    return response


def get_entry(db: Session, organization_id: UUID, memory_id: UUID) -> MemoryEntry:
    entry = db.scalar(
        select(MemoryEntry).where(
            MemoryEntry.id == memory_id, MemoryEntry.organization_id == organization_id
        )
    )
    if entry is None:
        raise APIError(404, "memory_not_found", "Memory not found.")
    return entry


def entry_detail(db: Session, entry: MemoryEntry) -> MemoryResponse:
    org = entry.organization_id
    title = (
        db.scalar(
            select(MemoryThread.title).where(
                MemoryThread.id == entry.thread_id, MemoryThread.organization_id == org
            )
        )
        if entry.thread_id
        else None
    )
    agent = (
        db.scalar(
            select(Agent.name).where(Agent.id == entry.agent_id, Agent.organization_id == org)
        )
        if entry.agent_id
        else None
    )
    return memory_response(entry, title, agent)


def list_memory(
    db: Session,
    organization_id: UUID,
    *,
    memory_type: MemoryType | None,
    scope: MemoryScope | None,
    thread_id: UUID | None,
    agent_id: UUID | None,
    active: bool | None,
    source_type: MemorySource | None,
    limit: int,
) -> list[MemoryResponse]:
    # Entries of evaluation threads (M10) are evaluation artifacts, not user memory.
    query = (
        select(MemoryEntry)
        .outerjoin(
            MemoryThread,
            (MemoryThread.id == MemoryEntry.thread_id)
            & (MemoryThread.organization_id == MemoryEntry.organization_id),
        )
        .where(
            MemoryEntry.organization_id == organization_id,
            MemoryThread.evaluation_run_id.is_(None),
        )
    )
    for column, value in (
        (MemoryEntry.memory_type, memory_type),
        (MemoryEntry.scope, scope),
        (MemoryEntry.thread_id, thread_id),
        (MemoryEntry.agent_id, agent_id),
        (MemoryEntry.is_active, active),
        (MemoryEntry.source_type, source_type),
    ):
        if value is not None:
            query = query.where(column == value)
    entries = db.scalars(query.order_by(MemoryEntry.updated_at.desc(), MemoryEntry.id).limit(limit))
    return [memory_response(entry) for entry in entries]


def create_memory(
    db: Session, membership: OrganizationMembership, data: MemoryCreate
) -> MemoryResponse:
    org = membership.organization_id
    if data.scope != MemoryScope.THREAD and not manager(membership):
        raise APIError(
            403, "forbidden", "Only owners and admins can create agent or workspace memory."
        )
    reject_secrets(data.content, data.fact_value)
    thread = get_thread(db, org, data.thread_id) if data.thread_id else None
    if thread is not None and thread.status != ThreadStatus.ACTIVE:
        raise APIError(409, "thread_archived", "The thread is archived.")
    if (
        data.agent_id is not None
        and db.scalar(
            select(Agent.id).where(Agent.id == data.agent_id, Agent.organization_id == org)
        )
        is None
    ):
        raise APIError(404, "agent_not_found", "Agent not found.")
    owner = data.thread_id or data.agent_id or "workspace"
    fact = data.fact_key is not None
    if fact:
        memory_type = MemoryType.FACT
    else:
        memory_type = {
            MemoryScope.THREAD: MemoryType.THREAD,
            MemoryScope.AGENT: MemoryType.AGENT,
            MemoryScope.WORKSPACE: MemoryType.WORKSPACE,
        }[data.scope]
    value = clean(data.fact_value, 500) if fact else None
    content = clean(data.content or f"{data.fact_key}: {value}", 2000)
    entry = MemoryEntry(
        organization_id=org,
        memory_type=memory_type,
        scope=data.scope,
        thread_id=data.thread_id,
        agent_id=data.agent_id,
        fact_key=data.fact_key,
        fact_value=value,
        confidence=1.0 if fact else None,
        content=content,
        summary=clean(content, 300),
        importance=data.importance,
        pinned=data.pinned,
        source_type=MemorySource.MANUAL,
        created_by_user_id=membership.user_id,
        # Manual facts share the run writers' key, so one fact per key and scope exists.
        idempotency_key=f"{data.scope.value}:{owner}:fact:{data.fact_key}" if fact else None,
        expires_at=data.expires_at,
    )
    db.add(entry)
    if thread is not None:
        thread.last_activity_at = now()
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise APIError(
            409, "memory_fact_exists", "That fact already exists in this scope; update it."
        ) from error
    db.refresh(entry)
    return entry_detail(db, entry)


def can_modify(membership: OrganizationMembership, entry: MemoryEntry) -> bool:
    return manager(membership) or (
        entry.source_type == MemorySource.MANUAL and entry.created_by_user_id == membership.user_id
    )


def update_memory(
    db: Session, membership: OrganizationMembership, memory_id: UUID, data: MemoryUpdate
) -> MemoryResponse:
    entry = get_entry(db, membership.organization_id, memory_id)
    if not can_modify(membership, entry):
        raise APIError(403, "forbidden", "You cannot change this memory.")
    edits = data.model_dump(exclude_unset=True)
    content_edit = {"content", "fact_value"} & edits.keys()
    if content_edit and entry.source_type != MemorySource.MANUAL:
        # Run-derived memory keeps its recorded content; it can only be (de)activated/ranked.
        raise APIError(409, "memory_not_editable", "Only manual memory content can be edited.")
    if "fact_value" in edits and entry.fact_key is None:
        raise APIError(422, "memory_not_fact", "Only facts have a fact_value.")
    reject_secrets(edits.get("content"), edits.get("fact_value"))
    if edits.get("fact_value") is not None:
        entry.fact_value = clean(edits["fact_value"], 500)
        entry.content = f"{entry.fact_key}: {entry.fact_value}"
        entry.summary = clean(entry.content, 300)
    if edits.get("content") is not None:
        entry.content = clean(edits["content"], 2000)
        entry.summary = clean(entry.content, 300)
    for name in ("importance", "pinned"):
        if edits.get(name) is not None:
            setattr(entry, name, edits[name])
    if "expires_at" in edits:
        entry.expires_at = edits["expires_at"]
    if edits.get("is_active") is not None:
        entry.is_active = edits["is_active"]
        entry.deactivated_at = None if entry.is_active else now()
    db.commit()
    db.refresh(entry)
    return entry_detail(db, entry)


def delete_memory(
    db: Session, membership: OrganizationMembership, memory_id: UUID
) -> MemoryDeleted:
    entry = get_entry(db, membership.organization_id, memory_id)
    if not can_modify(membership, entry):
        raise APIError(403, "forbidden", "You cannot delete this memory.")
    if entry.source_type == MemorySource.MANUAL:
        db.delete(entry)
        db.commit()
        return MemoryDeleted(id=memory_id, outcome="deleted")
    entry.is_active = False
    entry.deactivated_at = now()
    db.commit()
    return MemoryDeleted(id=memory_id, outcome="deactivated")
