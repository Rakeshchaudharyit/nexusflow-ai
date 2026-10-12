"use client";

import { authenticated, scoped } from "./auth";
import type { RunStatus } from "./agents";

export type JobStatus =
  | "queued"
  | "running"
  | "retrying"
  | "completed"
  | "failed"
  | "cancelled";
export type JobType = "single_agent_run" | "team_run" | "approval_action";

/** Mirrors the API's ExecutionInfo: a run's background job, without queue internals. */
export type ExecutionInfo = {
  job_id: string;
  job_type: JobType;
  status: JobStatus;
  attempt: number;
  max_attempts: number;
  enqueued_at: string | null;
  started_at: string | null;
  heartbeat_at: string | null;
  next_retry_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  cancellation_requested: boolean;
  delivery_pending: boolean;
};
export type CancelResponse = {
  run_id: string;
  status: RunStatus | "awaiting_approval";
  cancellation_requested: boolean;
  execution: ExecutionInfo | null;
};

const id = (value: string) => encodeURIComponent(value);

export const cancelRun = (organizationId: string, runId: string) =>
  authenticated<CancelResponse>(
    `/agent-runs/${id(runId)}/cancel`,
    scoped(organizationId, { method: "POST" }),
  );
export const cancelTeamRun = (organizationId: string, runId: string) =>
  authenticated<CancelResponse>(
    `/agent-team-runs/${id(runId)}/cancel`,
    scoped(organizationId, { method: "POST" }),
  );
