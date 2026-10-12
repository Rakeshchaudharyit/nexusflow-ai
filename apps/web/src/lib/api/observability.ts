"use client";

import { authenticated, scoped } from "./auth";

export type SpanType =
  | "worker"
  | "graph_node"
  | "agent"
  | "tool"
  | "mcp"
  | "knowledge_search"
  | "memory_retrieval"
  | "policy"
  | "approval"
  | "action"
  | "retry";
export type SpanStatus = "completed" | "failed" | "cancelled" | "pending" | "lost";
export type TraceOrigin = "user" | "evaluation" | "all";

/** Mirrors the API's TraceSummary; status and timings come from the run row. */
export type TraceSummary = {
  id: string;
  run_type: "agent" | "team";
  run_id: string;
  origin: "user" | "evaluation";
  evaluation_run_id: string | null;
  agent_id: string | null;
  team_id: string | null;
  target_name: string | null;
  thread_id: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_category: string | null;
  attempt_count: number;
  queue_wait_ms: number | null;
  retry_count: number;
  span_count: number;
  created_at: string;
};
export type Span = {
  id: string;
  parent_span_id: string | null;
  span_type: SpanType;
  name: string;
  sequence: number;
  status: SpanStatus;
  attempt: number | null;
  agent_id: string | null;
  tool_key: string | null;
  mcp_server_id: string | null;
  knowledge_source_id: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  offset_ms: number;
  input_summary: string | null;
  output_summary: string | null;
  metadata: Record<string, unknown>;
  error_code: string | null;
  error_category: string | null;
  error_message: string | null;
};
export type TraceJob = {
  id: string;
  job_type: string;
  status: string;
  attempt: number;
  max_attempts: number;
  worker_id: string | null;
  created_at: string;
  enqueued_at: string | null;
  started_at: string | null;
  heartbeat_at: string | null;
  completed_at: string | null;
  next_retry_at: string | null;
  execution_ms: number | null;
  error_code: string | null;
  error_category: string | null;
  error_message: string | null;
};
export type TraceDetail = TraceSummary & {
  run_label: string;
  error_message: string | null;
  jobs: TraceJob[];
  attempts: {
    attempt: number;
    job_type: string | null;
    status: string;
    duration_ms: number | null;
    worker_id: string | null;
    error_code: string | null;
    error_category: string | null;
  }[];
  spans: Span[];
  failing_spans: string[];
  total_ms: number;
};
export type CountByKey = {
  key: string;
  count: number;
  failures: number;
  avg_duration_ms: number | null;
};
export type ObservabilitySummary = {
  window_hours: number;
  since: string;
  runs: number;
  by_status: Record<string, number>;
  by_run_type: Record<string, number>;
  completed: number;
  failed: number;
  avg_duration_ms: number | null;
  max_duration_ms: number | null;
  avg_queue_wait_ms: number | null;
  max_queue_wait_ms: number | null;
  retries: number;
  runs_with_retries: number;
  errors_by_category: CountByKey[];
  tool_usage: CountByKey[];
  knowledge_searches: number;
  knowledge_no_match: number;
  knowledge_avg_results: number | null;
  approvals: Record<string, number>;
};
export type TraceFilters = {
  run_type?: "agent" | "team";
  status?: string;
  origin?: TraceOrigin;
  since?: string;
  run_id?: string;
  error_category?: string;
  limit?: number;
};

const query = (filters: Record<string, unknown>) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters))
    if (value !== undefined && value !== "") params.set(key, String(value));
  return params.size ? `?${params}` : "";
};

export const listTraces = (organizationId: string, filters: TraceFilters = {}) =>
  authenticated<TraceSummary[]>(`/traces${query(filters)}`, scoped(organizationId));
export const getTrace = (organizationId: string, traceId: string) =>
  authenticated<TraceDetail>(`/traces/${encodeURIComponent(traceId)}`, scoped(organizationId));
export const getObservabilitySummary = (organizationId: string, hours = 24) =>
  authenticated<ObservabilitySummary>(
    `/observability/summary${query({ hours })}`,
    scoped(organizationId),
  );
