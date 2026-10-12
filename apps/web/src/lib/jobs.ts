import type { ExecutionInfo, JobStatus } from "./api/jobs";

/** Bounded polling cadence for runs that are still queued or running (no WebSockets in M7). */
export const POLL_INTERVAL_MS = 2000;

type LifecycleStatus = string;

/** Polling continues only while the worker may still change the run. */
export const isRunActive = (status: LifecycleStatus) =>
  status === "queued" || status === "running";

export const isCancellable = (status: LifecycleStatus) =>
  isRunActive(status) || status === "awaiting_approval";

/** A queued run whose job is waiting out a retry delay is shown as "retrying". */
export function displayStatus<S extends string>(
  status: S,
  executionStatus: JobStatus | null | undefined,
): S | "retrying" {
  return status === "queued" && executionStatus === "retrying"
    ? "retrying"
    : status;
}

/** One honest sentence about where the background job stands; null when nothing to add. */
export function executionNote(execution: ExecutionInfo | null): string | null {
  if (!execution) return null;
  if (execution.status === "queued" && execution.delivery_pending)
    return "Saved but not yet handed to the queue. It will be delivered automatically when the queue is reachable.";
  if (execution.status === "queued")
    return "Queued. Waiting for a worker to pick it up.";
  if (execution.status === "running" && execution.cancellation_requested)
    return "Cancellation requested. The worker stops at the next stage.";
  if (execution.status === "running")
    return `Running on a worker (attempt ${execution.attempt} of ${execution.max_attempts}).`;
  if (execution.status === "retrying")
    return `Attempt ${execution.attempt} of ${execution.max_attempts} hit a temporary failure${
      execution.error_message ? `: ${execution.error_message}` : "."
    } Retrying automatically.`;
  return null;
}
