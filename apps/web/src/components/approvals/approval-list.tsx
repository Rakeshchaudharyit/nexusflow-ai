"use client";

import { LoadingState, RiskBadge } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback, useState } from "react";
import { formatDate, preview, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { useWorkspace } from "@/components/workspace-shell";
import { actionLabel, SIMULATION_NOTICE } from "@/lib/actions";
import {
  listApprovals,
  type ApprovalStatus,
  type RiskLevel,
} from "@/lib/api/approvals";

const STATUSES: ApprovalStatus[] = [
  "pending",
  "approved",
  "rejected",
  "expired",
];
const RISKS: RiskLevel[] = ["low", "medium", "high"];

export function ApprovalList() {
  const organization = useWorkspace();
  const [status, setStatus] = useState<ApprovalStatus | "">("pending");
  const [risk, setRisk] = useState<RiskLevel | "">("");
  const load = useCallback(
    () =>
      listApprovals(organization.id, {
        status: status || undefined,
        risk_level: risk || undefined,
      }),
    [organization.id, status, risk],
  );
  const { data: approvals, error, loading, reload } = useResource(load);
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">APPROVALS / {organization.name}</p>
          <h1>Approval inbox</h1>
        </div>
        <button onClick={reload}>Refresh</button>
      </div>
      <p className="muted-text">
        Business actions proposed by team runs that policy holds for human
        review. {SIMULATION_NOTICE}
      </p>
      <div className="filter-row">
        <label>
          Status
          <select
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as ApprovalStatus | "")
            }
          >
            <option value="">All statuses</option>
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          Risk
          <select
            value={risk}
            onChange={(event) => setRisk(event.target.value as RiskLevel | "")}
          >
            <option value="">All risks</option>
            {RISKS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {loading && <LoadingState />}
      {approvals && approvals.length === 0 && (
        <p className="muted-text">
          No approvals match these filters. Approvals appear when a{" "}
          <Link href="/app/team-runs">team run</Link> proposes an action that
          policy holds for review.
        </p>
      )}
      {approvals && approvals.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Action</th>
                <th>Risk</th>
                <th>Team / objective</th>
                <th>Created</th>
                <th>Expires</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {approvals.map((approval) => (
                <tr key={approval.id}>
                  <td>
                    <Link href={`/app/approvals/${approval.id}`}>
                      {actionLabel(approval.action_type)}
                    </Link>
                  </td>
                  <td><RiskBadge risk={approval.risk_level}/></td>
                  <td>
                    {approval.team_name ?? "Team"}
                    <div className="muted-text">
                      {preview(approval.objective ?? "", 70)}
                    </div>
                  </td>
                  <td className="nowrap">{formatDate(approval.created_at)}</td>
                  <td className="nowrap">
                    {approval.status === "pending"
                      ? formatDate(approval.expires_at)
                      : "—"}
                  </td>
                  <td>
                    <StatusPill status={approval.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
