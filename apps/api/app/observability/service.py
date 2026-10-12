"""Trace and metrics queries. Every query is scoped to the caller's organization: traces,
spans, jobs and aggregates of another organization are unreachable (404 or simply absent)."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.models.agents import Agent, AgentRun
from app.models.approvals import ApprovalRequest
from app.models.jobs import ExecutionJob
from app.models.observability import RunTrace, SpanStatus, SpanType, TraceRunType, TraceSpan
from app.models.teams import AgentTeam, AgentTeamRun
from app.observability.errors import categorize
from app.observability.redact import clip
from app.schemas.observability import (
    AttemptInfo,
    CountByKey,
    JobInfo,
    ObservabilitySummary,
    SpanResponse,
    TraceDetail,
    TraceSummary,
)

MAX_LIMIT = 100


def _base(organization_id: UUID):
    status = func.coalesce(AgentRun.status, AgentTeamRun.status)
    return (
        select(
            RunTrace,
            status.label("status"),
            func.coalesce(AgentRun.started_at, AgentTeamRun.started_at).label("started_at"),
            func.coalesce(AgentRun.completed_at, AgentTeamRun.completed_at).label("completed_at"),
            func.coalesce(AgentRun.duration_ms, AgentTeamRun.duration_ms).label("duration_ms"),
            func.coalesce(AgentRun.error_code, AgentTeamRun.error_code).label("error_code"),
            func.coalesce(AgentRun.error_message, AgentTeamRun.error_message).label(
                "error_message"
            ),
            func.coalesce(Agent.name, AgentTeam.name).label("target_name"),
            AgentRun.input_text,
            AgentTeamRun.objective,
        )
        .outerjoin(
            AgentRun,
            and_(
                AgentRun.id == RunTrace.agent_run_id,
                AgentRun.organization_id == RunTrace.organization_id,
            ),
        )
        .outerjoin(
            AgentTeamRun,
            and_(
                AgentTeamRun.id == RunTrace.team_run_id,
                AgentTeamRun.organization_id == RunTrace.organization_id,
            ),
        )
        .outerjoin(
            Agent, and_(Agent.id == AgentRun.agent_id, Agent.organization_id == organization_id)
        )
        .outerjoin(
            AgentTeam,
            and_(
                AgentTeam.id == AgentTeamRun.team_id, AgentTeam.organization_id == organization_id
            ),
        )
        .where(RunTrace.organization_id == organization_id)
    ), status


def _summary(row) -> TraceSummary:
    trace = row.RunTrace
    status = row.status.value if hasattr(row.status, "value") else str(row.status)
    return TraceSummary(
        id=trace.id,
        run_type=trace.run_type.value,
        run_id=trace.agent_run_id or trace.team_run_id,
        origin="evaluation" if trace.evaluation_run_id else "user",
        evaluation_run_id=trace.evaluation_run_id,
        agent_id=trace.agent_id,
        team_id=trace.team_id,
        target_name=row.target_name,
        thread_id=trace.thread_id,
        status=status,
        started_at=row.started_at,
        completed_at=row.completed_at,
        duration_ms=row.duration_ms,
        error_code=row.error_code,
        error_category=categorize(row.error_code),
        attempt_count=trace.attempt_count,
        queue_wait_ms=trace.queue_wait_ms,
        retry_count=trace.retry_count,
        span_count=trace.span_count,
        created_at=trace.created_at,
    )


def list_traces(
    db: Session,
    organization_id: UUID,
    *,
    run_type: TraceRunType | None = None,
    status: str | None = None,
    agent_id: UUID | None = None,
    team_id: UUID | None = None,
    error_code: str | None = None,
    error_category: str | None = None,
    run_id: UUID | None = None,
    origin: str = "user",
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TraceSummary]:
    query, status_column = _base(organization_id)
    filters = [
        (RunTrace.run_type, run_type),
        (RunTrace.agent_id, agent_id),
        (RunTrace.team_id, team_id),
    ]
    for column, value in filters:
        if value is not None:
            query = query.where(column == value)
    if status:
        query = query.where(status_column == status)
    if error_code:
        query = query.where(
            func.coalesce(AgentRun.error_code, AgentTeamRun.error_code) == error_code
        )
    if run_id:
        query = query.where(or_(RunTrace.agent_run_id == run_id, RunTrace.team_run_id == run_id))
    if origin == "user":
        query = query.where(RunTrace.evaluation_run_id.is_(None))
    elif origin == "evaluation":
        query = query.where(RunTrace.evaluation_run_id.is_not(None))
    if since:
        query = query.where(RunTrace.created_at >= since)
    if until:
        query = query.where(RunTrace.created_at <= until)
    rows = db.execute(
        query.order_by(RunTrace.created_at.desc(), RunTrace.id)
        .limit(min(limit, MAX_LIMIT))
        .offset(max(offset, 0))
    ).all()
    traces = [_summary(row) for row in rows]
    if error_category:
        traces = [trace for trace in traces if trace.error_category == error_category]
    return traces


def _aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _ms(start, end) -> float | None:
    start, end = _aware(start), _aware(end)
    return max(0.0, round((end - start).total_seconds() * 1000, 3)) if start and end else None


def get_trace(db: Session, organization_id: UUID, trace_id: UUID) -> TraceDetail:
    query, _ = _base(organization_id)
    row = db.execute(query.where(RunTrace.id == trace_id)).first()
    if row is None:
        raise APIError(404, "trace_not_found", "Trace not found.")
    trace = row.RunTrace
    spans = list(
        db.scalars(
            select(TraceSpan)
            .where(TraceSpan.trace_id == trace.id, TraceSpan.organization_id == organization_id)
            .order_by(TraceSpan.sequence)
            .limit(1000)
        )
    )
    origin = min((_aware(span.started_at) for span in spans), default=None)
    end = max((_aware(span.completed_at or span.started_at) for span in spans), default=origin)
    resource = (
        ExecutionJob.agent_run_id == trace.agent_run_id
        if trace.agent_run_id
        else ExecutionJob.team_run_id == trace.team_run_id
    )
    jobs = list(
        db.scalars(
            select(ExecutionJob)
            .where(resource, ExecutionJob.organization_id == organization_id)
            .order_by(ExecutionJob.created_at, ExecutionJob.id)
        )
    )
    workers = [span for span in spans if span.span_type == SpanType.WORKER]
    summary = _summary(row)
    return TraceDetail(
        **summary.model_dump(),
        run_label=clip(row.input_text or row.objective or "", 200) or "",
        error_message=row.error_message,
        jobs=[
            JobInfo(
                id=job.id,
                job_type=job.job_type.value,
                status=job.status.value,
                attempt=job.attempt,
                max_attempts=job.max_attempts,
                worker_id=job.worker_id,
                created_at=job.created_at,
                enqueued_at=job.enqueued_at,
                started_at=job.started_at,
                heartbeat_at=job.heartbeat_at,
                completed_at=job.completed_at,
                next_retry_at=job.next_retry_at,
                execution_ms=_ms(job.started_at, job.completed_at),
                error_code=job.error_code,
                error_category=categorize(job.error_code),
                error_message=job.error_message,
            )
            for job in jobs
        ],
        attempts=[
            AttemptInfo(
                attempt=span.attempt or 0,
                job_type=span.metadata_json.get("job_type"),
                status=span.status.value,
                duration_ms=span.duration_ms,
                worker_id=span.metadata_json.get("worker_id"),
                error_code=span.error_code,
                error_category=span.error_category,
            )
            for span in workers
        ],
        spans=[
            SpanResponse(
                id=span.id,
                parent_span_id=span.parent_span_id,
                span_type=span.span_type.value,
                name=span.name,
                sequence=span.sequence,
                status=span.status.value,
                attempt=span.attempt,
                agent_id=span.agent_id,
                tool_key=span.tool_key,
                mcp_server_id=span.mcp_server_id,
                knowledge_source_id=span.knowledge_source_id,
                started_at=span.started_at,
                completed_at=span.completed_at,
                duration_ms=span.duration_ms,
                offset_ms=_ms(origin, span.started_at) or 0,
                input_summary=span.input_summary,
                output_summary=span.output_summary,
                metadata=span.metadata_json or {},
                error_code=span.error_code,
                error_category=span.error_category,
                error_message=span.error_message,
            )
            for span in spans
        ],
        failing_spans=[
            span.id
            for span in spans
            if span.status in (SpanStatus.FAILED, SpanStatus.LOST) and span.error_code
        ],
        total_ms=_ms(origin, end) or 0,
    )


def summary(
    db: Session, organization_id: UUID, hours: int = 24, origin: str = "user"
) -> ObservabilitySummary:
    """Aggregates over traces created in the window. All values derive from stored rows."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    query, _ = _base(organization_id)
    query = query.where(RunTrace.created_at >= since)
    if origin == "user":
        query = query.where(RunTrace.evaluation_run_id.is_(None))
    rows = db.execute(query.limit(5000)).all()
    by_status: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    durations, waits = [], []
    categories: dict[str, int] = defaultdict(int)
    retries = with_retries = 0
    for row in rows:
        trace = row.RunTrace
        status = row.status.value if hasattr(row.status, "value") else str(row.status)
        by_status[status] += 1
        by_type[trace.run_type.value] += 1
        if status == "completed" and row.duration_ms is not None:
            durations.append(row.duration_ms)
        if trace.queue_wait_ms is not None:
            waits.append(trace.queue_wait_ms)
        retries += trace.retry_count or 0
        with_retries += 1 if trace.retry_count else 0
        if status == "failed":
            categories[categorize(row.error_code) or "internal"] += 1
    trace_ids = [row.RunTrace.id for row in rows]
    tools: dict[str, list] = defaultdict(lambda: [0, 0, 0])
    knowledge = no_match = results = 0
    if trace_ids:
        for span in db.scalars(
            select(TraceSpan)
            .where(
                TraceSpan.organization_id == organization_id,
                TraceSpan.trace_id.in_(trace_ids),
                TraceSpan.span_type.in_((SpanType.TOOL, SpanType.MCP, SpanType.KNOWLEDGE_SEARCH)),
            )
            .limit(20000)
        ):
            entry = tools[span.tool_key or span.name]
            entry[0] += 1
            entry[1] += 1 if span.status == SpanStatus.FAILED else 0
            entry[2] += span.duration_ms or 0
            if span.span_type == SpanType.KNOWLEDGE_SEARCH and span.status == SpanStatus.COMPLETED:
                knowledge += 1
                no_match += 1 if span.metadata_json.get("insufficient") else 0
                results += span.metadata_json.get("results") or 0
    approvals_query = (
        select(ApprovalRequest.status, func.count())
        .join(
            AgentTeamRun,
            and_(
                AgentTeamRun.id == ApprovalRequest.team_run_id,
                AgentTeamRun.organization_id == ApprovalRequest.organization_id,
            ),
        )
        .where(
            ApprovalRequest.organization_id == organization_id,
            ApprovalRequest.created_at >= since,
        )
        .group_by(ApprovalRequest.status)
    )
    if origin == "user":
        approvals_query = approvals_query.where(AgentTeamRun.evaluation_run_id.is_(None))
    approvals = {status.value: count for status, count in db.execute(approvals_query)}
    return ObservabilitySummary(
        window_hours=hours,
        since=since,
        runs=len(rows),
        by_status=dict(by_status),
        by_run_type=dict(by_type),
        completed=by_status.get("completed", 0),
        failed=by_status.get("failed", 0),
        avg_duration_ms=round(sum(durations) / len(durations), 1) if durations else None,
        max_duration_ms=max(durations) if durations else None,
        avg_queue_wait_ms=round(sum(waits) / len(waits), 1) if waits else None,
        max_queue_wait_ms=max(waits) if waits else None,
        retries=retries,
        runs_with_retries=with_retries,
        errors_by_category=sorted(
            (CountByKey(key=key, count=count) for key, count in categories.items()),
            key=lambda item: (-item.count, item.key),
        ),
        tool_usage=sorted(
            (
                CountByKey(
                    key=key,
                    count=count,
                    failures=failures,
                    avg_duration_ms=round(total / count, 1) if count else None,
                )
                for key, (count, failures, total) in tools.items()
            ),
            key=lambda item: (-item.count, item.key),
        ),
        knowledge_searches=knowledge,
        knowledge_no_match=no_match,
        knowledge_avg_results=round(results / knowledge, 2) if knowledge else None,
        approvals=approvals,
    )
