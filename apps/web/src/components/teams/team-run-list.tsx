"use client";
import { displayStatus, isRunActive } from "@/lib/jobs";

import { LoadingState } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback } from "react";
import {
  formatDate,
  formatDuration,
  preview,
  usePolling,
  useResource,
} from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { useWorkspace } from "@/components/workspace-shell";
import { listTeamRuns } from "@/lib/api/teams";

export function TeamRunList() {
  const organization = useWorkspace();
  const load = useCallback(
    () => listTeamRuns(organization.id),
    [organization.id],
  );
  const { data: runs, error, loading, reload } = useResource(load);
  // Refresh while any listed run is still with the worker (bounded polling).
  usePolling(!!runs?.some((run) => isRunActive(run.status)), reload);
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">TEAM RUNS / {organization.name}</p>
          <h1>Team run history</h1>
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
          No team runs in this workspace yet. Open a{" "}
          <Link href="/app/teams">team</Link> to run it.
        </p>
      )}
      {runs && runs.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Team</th>
                <th>Status</th>
                <th>Objective</th>
                <th>Duration</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td className="mono">
                    <Link href={`/app/team-runs/${run.id}`}>
                      {run.id.slice(0, 8)}
                    </Link>
                  </td>
                  <td>{run.team_name}</td>
                  <td>
                    <StatusPill status={displayStatus(run.status, run.execution_status)} />
                  </td>
                  <td className="muted-text">{preview(run.objective)}</td>
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
