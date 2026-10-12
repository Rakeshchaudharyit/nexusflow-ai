"use client";

import { useState } from "react";
import { describeError, formatDate } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { useAuth } from "@/components/auth-provider";
import { useWorkspace } from "@/components/workspace-shell";
import {
  cancelRun,
  cancelTeamRun,
  type ExecutionInfo,
} from "@/lib/api/jobs";
import { executionNote, isCancellable } from "@/lib/jobs";

type Props = {
  kind: "agent" | "team";
  runId: string;
  status: string;
  createdBy: string | null;
  execution: ExecutionInfo | null;
  onChanged: () => void;
};

/** Background-job view for a run (M7): lifecycle, attempts, heartbeat and cancellation. */
export function RunExecution({
  kind,
  runId,
  status,
  createdBy,
  execution,
  onChanged,
}: Props) {
  const organization = useWorkspace();
  const { user } = useAuth();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  // The API enforces the same rule; members may cancel only runs they started.
  const allowed =
    organization.role !== "member" || (!!user && createdBy === user.id);
  const note = executionNote(execution);

  async function cancel() {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await (kind === "agent" ? cancelRun : cancelTeamRun)(
        organization.id,
        runId,
      );
    } catch (problem) {
      setFailure(describeError(problem));
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  if (!execution && !isCancellable(status)) return null;
  return (
    <section className="panel" aria-live="polite">
      <h2>Background execution</h2>
      {note && <p className="muted-text">{note}</p>}
      {execution && (
        <dl className="details">
          <dt>Job</dt>
          <dd>
            <StatusPill status={execution.status} />{" "}
            <span className="mono muted-text">
              {execution.job_type.replaceAll("_", " ")}
            </span>
          </dd>
          <dt>Attempt</dt>
          <dd>
            {execution.attempt} of {execution.max_attempts}
          </dd>
          <dt>Started</dt>
          <dd>{formatDate(execution.started_at)}</dd>
          <dt>Last heartbeat</dt>
          <dd>{formatDate(execution.heartbeat_at)}</dd>
          {execution.next_retry_at && execution.status === "retrying" && (
            <>
              <dt>Next attempt</dt>
              <dd>{formatDate(execution.next_retry_at)}</dd>
            </>
          )}
          {execution.error_code && (
            <>
              <dt>Last error</dt>
              <dd>
                {execution.error_message}{" "}
                <span className="mono muted-text">({execution.error_code})</span>
              </dd>
            </>
          )}
        </dl>
      )}
      {failure && (
        <p className="form-error" role="alert">
          {failure}
        </p>
      )}
      {isCancellable(status) && allowed && (
        <div className="button-row">
          <button
            disabled={busy || execution?.cancellation_requested}
            onClick={() => void cancel()}
          >
            {busy
              ? "Cancelling…"
              : execution?.cancellation_requested
                ? "Cancellation requested"
                : "Cancel run"}
          </button>
        </div>
      )}
    </section>
  );
}
