"""In-memory span collection with monotonic timing, flushed once per attempt.

    tracer = Tracer(organization_id=..., agent_run_id=..., attempt=2)
    with tracer.span(SpanType.TOOL, "calculator", tool_key="internal:calculator"):
        ...
    tracer.flush(sessions)     # one short transaction, after the business commit

Durations come from time.perf_counter (monotonic); UTC wall-clock timestamps are captured
at span start and derived for the end. Graph nodes run sequentially, so a stack gives each
new span its parent. flush() never raises: tracing must not break execution.
"""

import logging
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.observability import RunTrace, SpanStatus, SpanType, TraceRunType, TraceSpan
from app.observability.errors import categorize
from app.observability.redact import clip, safe_metadata

logger = logging.getLogger(__name__)
MAX_SPANS_PER_FLUSH = 400
_CURRENT = object()


def elapsed(started: float) -> float:
    """Milliseconds since a perf_counter reading, to the microsecond."""
    return round((perf_counter() - started) * 1000, 3)


@dataclass
class Span:
    id: UUID
    parent_id: UUID | None
    span_type: SpanType
    name: str
    attempt: int | None
    started_at: datetime
    started: float
    status: SpanStatus = SpanStatus.COMPLETED
    duration_ms: float | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def open(self) -> bool:
        return self.duration_ms is None


class Tracer:
    def __init__(
        self,
        *,
        organization_id: UUID,
        agent_run_id: UUID | None = None,
        team_run_id: UUID | None = None,
        attempt: int | None = None,
    ):
        self.organization_id = organization_id
        self.agent_run_id = agent_run_id
        self.team_run_id = team_run_id
        self.attempt = attempt
        self.spans: list[Span] = []
        self._stack: list[Span] = []
        self._lock = Lock()
        self.queue_wait_ms: int | None = None
        self.retries = 0

    # --- recording ------------------------------------------------------------------------

    @property
    def current(self) -> Span | None:
        return self._stack[-1] if self._stack else None

    def open(self, span_type: SpanType, name: str, *, parent=_CURRENT, **fields) -> Span:
        with self._lock:
            parent_span = self.current if parent is _CURRENT else parent
            span = Span(
                id=uuid.uuid4(),
                parent_id=parent_span.id if parent_span is not None else None,
                span_type=span_type,
                name=clip(name, 120),
                attempt=self.attempt,
                started_at=datetime.now(UTC),
                started=perf_counter(),
                fields=fields,
            )
            self.spans.append(span)
            self._stack.append(span)
            return span

    def close(
        self,
        span: Span | None,
        status: SpanStatus = SpanStatus.COMPLETED,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        output_summary: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        if span is None or not span.open:
            return
        with self._lock:
            measured = elapsed(span.started)
            span.duration_ms = max(0, duration_ms if duration_ms is not None else measured)
            span.status = status
            if error_code:
                span.fields["error_code"] = error_code
                span.fields["error_message"] = error_message
            if output_summary is not None:
                span.fields["output_summary"] = output_summary
            if metadata:
                span.metadata.update(metadata)
            if span in self._stack:
                # Close any children still open above it (e.g. after an exception).
                while self._stack and self._stack[-1] is not span:
                    child = self._stack.pop()
                    if child.open:
                        child.duration_ms = elapsed(child.started)
                        child.status = SpanStatus.FAILED
                self._stack.pop()

    def add(
        self,
        span_type: SpanType,
        name: str,
        *,
        duration_ms: float = 0,
        status: SpanStatus = SpanStatus.COMPLETED,
        parent=_CURRENT,
        metadata: Mapping[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        **fields,
    ) -> Span:
        """A span whose duration is already known (it ended just now)."""
        span = self.open(span_type, name, parent=parent, **fields)
        span.started_at = span.started_at - timedelta(milliseconds=duration_ms)
        self.close(
            span,
            status,
            duration_ms=duration_ms,
            metadata=metadata,
            error_code=error_code,
            error_message=error_message,
        )
        return span

    @contextmanager
    def span(self, span_type: SpanType, name: str, **fields) -> Iterator[Span]:
        span = self.open(span_type, name, **fields)
        try:
            yield span
        except BaseException as error:
            code = getattr(error, "code", None) or type(error).__name__.lower()[:80]
            self.close(
                span,
                SpanStatus.FAILED,
                error_code=code,
                error_message=getattr(error, "message", None),
            )
            raise
        self.close(span)

    def close_all(self, status: SpanStatus) -> None:
        while self._stack:
            self.close(self._stack[-1], status)

    # --- persistence ----------------------------------------------------------------------

    def _trace(self, db: Session) -> RunTrace | None:
        column = RunTrace.agent_run_id if self.agent_run_id is not None else RunTrace.team_run_id
        run_id = self.agent_run_id or self.team_run_id
        trace = db.scalar(
            select(RunTrace)
            .where(column == run_id, RunTrace.organization_id == self.organization_id)
            .with_for_update()
        )
        if trace is None:
            # Runs created before M10 have no trace yet; create it on first observation.
            trace = new_trace(
                self.organization_id,
                agent_run_id=self.agent_run_id,
                team_run_id=self.team_run_id,
            )
            db.add(trace)
            db.flush()
        return trace

    def flush(self, sessions: sessionmaker[Session] | None = None, db: Session | None = None):
        """Persist collected spans. Never raises; returns False if tracing failed."""
        if not self.spans:
            return True
        try:
            if db is not None:
                self._write(db)
                db.commit()
            else:
                with sessions() as session:
                    self._write(session)
                    session.commit()
            self.spans = []
            return True
        except Exception as error:  # observability must never break execution
            logger.warning(
                "Trace flush failed for run %s (%s); spans dropped",
                self.agent_run_id or self.team_run_id,
                type(error).__name__,
            )
            if db is not None:
                db.rollback()
            return False

    def _write(self, db: Session) -> None:
        trace = self._trace(db)
        base = db.scalar(
            select(func.coalesce(func.max(TraceSpan.sequence), 0)).where(
                TraceSpan.trace_id == trace.id
            )
        )
        spans = self.spans[:MAX_SPANS_PER_FLUSH]
        last_category = None
        for offset, span in enumerate(spans, start=1):
            if span.open:
                span.duration_ms = elapsed(span.started)
                span.status = SpanStatus.CANCELLED
            code = span.fields.get("error_code")
            category = categorize(code)
            last_category = category or last_category
            db.add(
                TraceSpan(
                    id=span.id,
                    organization_id=self.organization_id,
                    trace_id=trace.id,
                    parent_span_id=span.parent_id,
                    span_type=span.span_type,
                    name=span.name,
                    sequence=base + offset,
                    status=span.status,
                    attempt=span.attempt,
                    agent_id=span.fields.get("agent_id"),
                    tool_key=clip(span.fields.get("tool_key"), 300),
                    mcp_server_id=span.fields.get("mcp_server_id"),
                    knowledge_source_id=span.fields.get("knowledge_source_id"),
                    started_at=span.started_at,
                    completed_at=span.started_at + timedelta(milliseconds=span.duration_ms or 0),
                    duration_ms=span.duration_ms,
                    input_summary=clip(span.fields.get("input_summary")),
                    output_summary=clip(span.fields.get("output_summary")),
                    metadata_json=safe_metadata(span.metadata),
                    error_code=clip(code, 80),
                    error_category=category,
                    error_message=clip(span.fields.get("error_message"), 300),
                )
            )
            # Parents are inserted before children (creation order), as the FK requires.
            db.flush()
        if self.attempt is not None:
            trace.attempt_count = max(trace.attempt_count or 0, self.attempt)
        if self.queue_wait_ms is not None and trace.queue_wait_ms is None:
            trace.queue_wait_ms = self.queue_wait_ms
        trace.retry_count = (trace.retry_count or 0) + self.retries
        trace.span_count = (trace.span_count or 0) + len(spans)
        if last_category:
            trace.last_error_category = last_category


def new_trace(
    organization_id: UUID,
    *,
    agent_run_id: UUID | None = None,
    team_run_id: UUID | None = None,
    agent_id: UUID | None = None,
    team_id: UUID | None = None,
    thread_id: UUID | None = None,
    evaluation_run_id: UUID | None = None,
) -> RunTrace:
    return RunTrace(
        organization_id=organization_id,
        run_type=TraceRunType.AGENT if agent_run_id is not None else TraceRunType.TEAM,
        agent_run_id=agent_run_id,
        team_run_id=team_run_id,
        agent_id=agent_id,
        team_id=team_id,
        thread_id=thread_id,
        evaluation_run_id=evaluation_run_id,
    )


def keys(payload: Mapping[str, Any] | None) -> str | None:
    """'keys: a, b' (names only, never values) for node/handoff payloads."""
    if not payload:
        return None
    return clip("keys: " + ", ".join(sorted(str(key) for key in payload)[:12]))


def node_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A few safe scalars from a graph node's state update."""
    metadata: dict[str, Any] = {}
    if "intent" in payload:
        metadata["intent"] = payload["intent"]
    if "tool_source" in payload:
        metadata["tool_source"] = payload["tool_source"]
    if isinstance(payload.get("plan"), list):
        metadata["plan_steps"] = len(payload["plan"])
        metadata["tools_planned"] = [
            step.get("tool_key") for step in payload["plan"] if step.get("tool_key")
        ]
    if isinstance(payload.get("tool_results"), list):
        metadata["tool_calls"] = len(payload["tool_results"])
    final = payload.get("final_output")
    if isinstance(final, Mapping):
        metadata["intent"] = final.get("intent")
        metadata["tools_used"] = list(final.get("tools_used") or [])
        if "citations" in final:
            metadata["citations"] = len(final.get("citations") or [])
    return metadata


def memory_metadata(usage: Mapping[str, Any]) -> dict[str, Any]:
    """Counts only (M8 usage); the injected memory text is never stored in a trace."""
    return {
        "thread_entries": usage.get("thread"),
        "agent_entries": usage.get("agent"),
        "workspace_entries": usage.get("workspace"),
        "workspace_enabled": usage.get("workspace_enabled"),
        "facts": usage.get("facts"),
        "summary_used": usage.get("summary"),
        "context_chars": usage.get("chars"),
        "truncated": usage.get("truncated"),
    }


def agent_metadata(role: str, output: Mapping[str, Any], tool_calls: list) -> dict[str, Any]:
    """Safe scalars from a team member's structured output."""
    metadata: dict[str, Any] = {"role": role, "tool_calls": len(tool_calls)}
    for key in ("found", "opportunity_score", "valid", "confidence", "revision"):
        if key in output:
            metadata[key] = output[key]
    if isinstance(output.get("signals"), list):
        metadata["signals"] = len(output["signals"])
    knowledge = output.get("knowledge")
    if isinstance(knowledge, Mapping):
        metadata["knowledge_results"] = len(knowledge.get("results") or [])
    if isinstance(output.get("citations"), list):
        metadata["citations"] = len(output["citations"])
    if isinstance(output.get("issues"), list):
        metadata["issues"] = len(output["issues"])
    return metadata


def record_recovery(
    sessions: sessionmaker[Session],
    *,
    organization_id: UUID,
    agent_run_id: UUID | None,
    team_run_id: UUID | None,
    attempt: int,
    max_attempts: int,
    started_at: datetime | None,
    heartbeat_at: datetime | None,
    outcome: str,
) -> None:
    """A recovered (dead) attempt never flushed its own spans. Record what is known for
    certain: when it started, its last heartbeat, and what recovery did. Best effort."""
    tracer = Tracer(
        organization_id=organization_id,
        agent_run_id=agent_run_id,
        team_run_id=team_run_id,
        attempt=attempt,
    )
    start = _aware(started_at)
    last = _aware(heartbeat_at) or start
    duration = max(0, round((last - start).total_seconds() * 1000)) if start and last else 0
    lost = tracer.add(
        SpanType.WORKER,
        f"Attempt {attempt} · worker lost",
        duration_ms=duration,
        status=SpanStatus.LOST,
        parent=None,
        error_code="worker_lost",
        error_message="The worker stopped heartbeating during this attempt.",
        metadata={"attempt": attempt, "last_heartbeat_at": last.isoformat() if last else None},
    )
    if start is not None:
        lost.started_at = start
    tracer.add(
        SpanType.RETRY,
        "Recovered: re-queued" if outcome == "requeued" else f"Recovered: {outcome}",
        parent=None,
        status=SpanStatus.FAILED,
        error_code="worker_lost",
        metadata={
            "attempt": attempt,
            "max_attempts": max_attempts,
            "reason": "stale heartbeat (recovery)",
            "outcome": outcome,
            "retry_delay_ms": 0 if outcome == "requeued" else None,
        },
    )
    tracer.retries = 1 if outcome == "requeued" else 0
    tracer.flush(sessions)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
