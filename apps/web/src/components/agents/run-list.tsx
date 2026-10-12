"use client";
import { displayStatus, isRunActive } from "@/lib/jobs";

import { LoadingState } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback } from "react";
import { useWorkspace } from "@/components/workspace-shell";
import { listRuns } from "@/lib/api/agents";
import {
  formatDate,
  formatDuration,
  preview,
  usePolling,
  useResource,
} from "./resource";
import { StatusPill } from "./status-pill";

export function RunList() {
  const organization = useWorkspace();
  const load = useCallback(() => listRuns(organization.id), [organization.id]);
  const { data: runs, error, loading, reload } = useResource(load);
  // Refresh while any listed run is still with the worker (bounded polling).
  usePolling(!!runs?.some((run) => isRunActive(run.status)), reload);
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">RUNS / {organization.name}</p>
          <h1>Run history</h1>
        </div>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {loading && <LoadingState />}
      {runs && runs.length === 0 && (
        <p className="muted-text">
          No runs in this workspace yet. Open an{" "}
          <Link href="/app/agents">agent</Link> to run it.
        </p>
      )}
      {runs && runs.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Agent</th>
                <th>Status</th>
                <th>Input</th>
                <th>Duration</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td className="mono">
                    <Link href={`/app/runs/${run.id}`}>
                      {run.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>{run.agent_name}</td>
                  <td>
                    <StatusPill status={displayStatus(run.status, run.execution_status)} />
                  </td>
                  <td className="muted-text">{preview(run.input_text)}</td>
                  <td className="nowrap">{formatDuration(run.duration_ms)}</td>
                  <td className="nowrap">{formatDate(run.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
