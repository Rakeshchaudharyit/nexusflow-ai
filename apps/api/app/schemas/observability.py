from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class TraceSummary(BaseModel):
    id: UUID
    run_type: str
    run_id: UUID
    origin: str  # user | evaluation
    evaluation_run_id: UUID | None
    agent_id: UUID | None
    team_id: UUID | None
    target_name: str | None
    thread_id: UUID | None
    # Read live from the run row (authoritative).
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_code: str | None
    error_category: str | None
    # Observability-only values.
    attempt_count: int
    queue_wait_ms: int | None
    retry_count: int
    span_count: int
    created_at: datetime


class SpanResponse(BaseModel):
    id: UUID
    parent_span_id: UUID | None
    span_type: str
    name: str
    sequence: int
    status: str
    attempt: int | None
    agent_id: UUID | None
    tool_key: str | None
    mcp_server_id: UUID | None
    knowledge_source_id: UUID | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: float | None
    offset_ms: float  # from the trace's first span start, for the waterfall
    input_summary: str | None
    output_summary: str | None
    metadata: dict[str, Any]
    error_code: str | None
    error_category: str | None
    error_message: str | None


class JobInfo(BaseModel):
    id: UUID
    job_type: str
    status: str
    attempt: int
    max_attempts: int
    worker_id: str | None
    created_at: datetime
    enqueued_at: datetime | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    completed_at: datetime | None
    next_retry_at: datetime | None
    execution_ms: float | None  # last attempt: completed_at - started_at
    error_code: str | None
    error_category: str | None
    error_message: str | None


class AttemptInfo(BaseModel):
    attempt: int
    job_type: str | None
    status: str
    duration_ms: float | None
    worker_id: str | None
    error_code: str | None
    error_category: str | None


class TraceDetail(TraceSummary):
    run_label: str
    error_message: str | None
    jobs: list[JobInfo]
    attempts: list[AttemptInfo]
    spans: list[SpanResponse]
    failing_spans: list[UUID]
    total_ms: float


class CountByKey(BaseModel):
    key: str
    count: int
    failures: int = 0
    avg_duration_ms: float | None = None


class ObservabilitySummary(BaseModel):
    window_hours: int
    since: datetime
    runs: int
    by_status: dict[str, int]
    by_run_type: dict[str, int]
    completed: int
    failed: int
    avg_duration_ms: float | None
    max_duration_ms: int | None
    avg_queue_wait_ms: float | None
    max_queue_wait_ms: int | None
    retries: int
    runs_with_retries: int
    errors_by_category: list[CountByKey]
    tool_usage: list[CountByKey]
    knowledge_searches: int
    knowledge_no_match: int
    knowledge_avg_results: float | None
    approvals: dict[str, int]
