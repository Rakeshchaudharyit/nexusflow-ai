"use client";

import { authenticated, scoped } from "./auth";
import type { ActionExecution, ApprovalStatus, TeamRunStatus } from "./teams";

export type { ApprovalStatus } from "./teams";
export type RiskLevel = "low" | "medium" | "high";

/** Mirrors the API's ApprovalResponse. */
export type Approval = {
  id: string;
  organization_id: string;
  team_run_id: string;
  team_id: string;
  team_name: string | null;
  objective: string | null;
  proposed_by_agent_id: string;
  agent_name: string | null;
  action_type: string;
  payload: Record<string, unknown>;
  risk_level: RiskLevel;
  rule_key: string;
  reason: string;
  status: ApprovalStatus;
  requested_by_user_id: string;
  reviewed_by_user_id: string | null;
  review_comment: string | null;
  created_at: string;
  updated_at: string;
  reviewed_at: string | null;
  expires_at: string;
  execution: ActionExecution | null;
  // M7: after approval the action runs in the worker; the run stays queued until it does.
  team_run_status: TeamRunStatus | null;
};
export type ApprovalFilters = {
  status?: ApprovalStatus;
  risk_level?: RiskLevel;
  team_run_id?: string;
  limit?: number;
};

const id = (value: string) => encodeURIComponent(value);
// Reviewers decide on the persisted payload; the API accepts only an optional comment.
const decide = (
  organizationId: string,
  approvalId: string,
  verb: string,
  comment?: string,
) =>
  authenticated<Approval>(
    `/approvals/${id(approvalId)}/${verb}`,
    scoped(organizationId, {
      method: "POST",
      body: JSON.stringify({ comment: comment?.trim() || null }),
    }),
  );

export const listApprovals = (
  organizationId: string,
  filters: ApprovalFilters = {},
) => {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters))
    if (value !== undefined && value !== "") query.set(key, String(value));
  const search = query.size ? `?${query}` : "";
  return authenticated<Approval[]>(
    `/approvals${search}`,
    scoped(organizationId),
  );
};
export const getApproval = (organizationId: string, approvalId: string) =>
  authenticated<Approval>(
    `/approvals/${id(approvalId)}`,
    scoped(organizationId),
  );
export const approveAction = (
  organizationId: string,
  approvalId: string,
  comment?: string,
) => decide(organizationId, approvalId, "approve", comment);
export const rejectAction = (
  organizationId: string,
  approvalId: string,
  comment?: string,
) => decide(organizationId, approvalId, "reject", comment);
