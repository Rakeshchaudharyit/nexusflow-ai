"use client";

import type {
  AgentStatus,
  AgentToolAssignment,
  RunError,
  RunEvent,
  RunStatus,
} from "./agents";
import { authenticated, scoped } from "./auth";
import type { Citation } from "./knowledge";
import type { ExecutionInfo, JobStatus } from "./jobs";
import type { MemoryUsage } from "./memory";

export type TeamStatus = "draft" | "active" | "archived";
// Team runs add one status to the single-agent set: paused until a human reviews an action.
export type TeamRunStatus = RunStatus | "awaiting_approval";
export type ActionDecision = "allow" | "require_approval" | "deny";
export type ActionStatus =
  | "awaiting_approval"
  | "completed"
  | "failed"
  | "denied"
  | "rejected"
  | "expired";
export type ApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "cancelled";
/** The business action a team run proposed and what policy and review did with it. */
export type TeamAction = {
  action_type: string;
  payload: Record<string, unknown>;
  decision: ActionDecision;
  rule_key: string;
  reason: string;
  risk_level: "low" | "medium" | "high";
  status: ActionStatus;
  approval_id: string | null;
  execution_id: string | null;
  message: string | null;
  simulated: true;
};
export type ActionExecution = {
  id: string;
  team_run_id: string;
  approval_request_id: string | null;
  action_type: string;
  payload: Record<string, unknown>;
  status: "completed" | "failed";
  result: { simulated: boolean; action_type: string; message: string };
  executed_by_user_id: string;
  created_at: string;
};
export type RunApproval = {
  approval_id: string | null;
  approval_status: ApprovalStatus | null;
  execution: ActionExecution | null;
};
export type TeamRole =
  | "supervisor"
  | "customer_specialist"
  | "researcher"
  | "analyst"
  | "writer"
  | "validator";

export type TeamMember = {
  id: string;
  agent_id: string;
  agent_name: string;
  agent_status: AgentStatus;
  role: TeamRole;
  position: number;
  is_required: boolean;
  tools: AgentToolAssignment[];
  /** M9: sources this member's agent may search (needs internal:knowledge_search). */
  knowledge_sources?: {
    source_id: string;
    source_name: string;
    source_status: string;
    is_enabled: boolean;
  }[];
};
export type Team = {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description: string;
  status: TeamStatus;
  workspace_memory_enabled: boolean;
  member_count: number;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
};
export type TeamDetail = Team & { members: TeamMember[]; problems: string[] };
export type TeamMemberInput = {
  agent_id: string;
  role: TeamRole;
  is_required?: boolean;
  position?: number;
};
export type TeamInput = {
  name: string;
  description: string;
  members: TeamMemberInput[];
};
export type TeamChanges = Partial<
  Pick<Team, "name" | "description" | "status" | "workspace_memory_enabled">
>;
export type TeamMemberChanges = Partial<
  Pick<TeamMember, "role" | "is_required" | "position">
>;

export type TeamOutput = {
  company: string;
  opportunity_score: number;
  summary: string;
  key_findings: string[];
  strengths: string[];
  risks: string[];
  recommended_next_steps: string[];
  validation: { valid: boolean; confidence: number; issues: string[] };
  sources: string[];
  agents: string[];
  revisions: number;
  /** M8: remembered notes the writer was given (labelled, never presented as facts). */
  memory_notes?: string[];
  /** M9: structured citations for the [K#] knowledge findings. */
  citations?: Citation[];
};
/** A run's stored output: the validated analysis (absent if a run ended before it) plus any
 * proposed action. */
export type TeamResultOutput = Partial<TeamOutput> & { action?: TeamAction };
export const hasAnalysis = (
  output: TeamResultOutput | null,
): output is TeamOutput & { action?: TeamAction } =>
  typeof output?.company === "string" &&
  Array.isArray(output.recommended_next_steps);

export type TeamRunResult = {
  run_id: string;
  team_id: string;
  status: TeamRunStatus;
  final_output: TeamResultOutput | null;
  agents_executed: string[];
  duration_ms: number | null;
  step_count: number;
  error: RunError | null;
  action: TeamAction | null;
  created_at: string | null;
  execution: ExecutionInfo | null;
  thread_id: string | null;
};
export type TeamRunSummary = {
  id: string;
  team_id: string;
  created_by_user_id: string | null;
  team_name: string;
  status: TeamRunStatus;
  objective: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  step_count: number;
  execution_status: JobStatus | null;
  thread_id: string | null;
};
export type PlanStep = {
  step: number;
  role: TeamRole;
  agent_id: string;
  agent_name: string;
  task: string;
};
export type AgentStepResult = {
  agent_id: string | null;
  agent_name: string | null;
  role: TeamRole;
  status: "completed" | "failed";
  output: Record<string, unknown> | null;
  tool_calls: Record<string, unknown>[];
  duration_ms: number | null;
  error: RunError | null;
};
export type Handoff = {
  sequence: number;
  to_role: TeamRole;
  agent_name: string | null;
  task: string;
  context: Record<string, unknown>;
};
export type TeamRunEvent = Omit<RunEvent, "event_type"> & {
  event_type:
    | "action_proposed"
    | "policy_allowed"
    | "policy_denied"
    | "approval_requested"
    | "approval_approved"
    | "approval_rejected"
    | "approval_expired"
    | "action_started"
    | "action_completed"
    | "action_failed"
    | "team_run_started"
    | "supervisor_plan_created"
    | "handoff_started"
    | "agent_completed"
    | "agent_failed"
    | "validation_failed"
    | "revision_requested"
    | "team_run_completed"
    | "team_run_failed"
    | "retry_scheduled"
    | "team_run_cancelled"
    | "memory_saved"
    | "memory_updated";
  agent_id: string | null;
  agent_role: TeamRole | null;
};
export type TeamRunDetail = TeamRunSummary & {
  plan: PlanStep[];
  final_output: TeamResultOutput | null;
  validation: { valid: boolean; confidence: number; issues: string[] } | null;
  revisions: number;
  results: AgentStepResult[];
  handoffs: Handoff[];
  error: RunError | null;
  action: TeamAction | null;
  approval: RunApproval | null;
  events: TeamRunEvent[];
  execution: ExecutionInfo | null;
  memory_context: MemoryUsage | null;
};

const id = (value: string) => encodeURIComponent(value);
const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

export const listTeams = (organizationId: string) =>
  authenticated<Team[]>("/agent-teams", scoped(organizationId));
export const getTeam = (organizationId: string, teamId: string) =>
  authenticated<TeamDetail>(
    `/agent-teams/${id(teamId)}`,
    scoped(organizationId),
  );
export const createTeam = (organizationId: string, input: TeamInput) =>
  authenticated<TeamDetail>(
    "/agent-teams",
    scoped(organizationId, json("POST", input)),
  );
export const updateTeam = (
  organizationId: string,
  teamId: string,
  changes: TeamChanges,
) =>
  authenticated<TeamDetail>(
    `/agent-teams/${id(teamId)}`,
    scoped(organizationId, json("PATCH", changes)),
  );
export const addTeamMember = (
  organizationId: string,
  teamId: string,
  member: TeamMemberInput,
) =>
  authenticated<TeamDetail>(
    `/agent-teams/${id(teamId)}/members`,
    scoped(organizationId, json("POST", member)),
  );
export const updateTeamMember = (
  organizationId: string,
  teamId: string,
  memberId: string,
  changes: TeamMemberChanges,
) =>
  authenticated<TeamDetail>(
    `/agent-teams/${id(teamId)}/members/${id(memberId)}`,
    scoped(organizationId, json("PATCH", changes)),
  );
export const removeTeamMember = (
  organizationId: string,
  teamId: string,
  memberId: string,
) =>
  authenticated<TeamDetail>(
    `/agent-teams/${id(teamId)}/members/${id(memberId)}`,
    scoped(organizationId, { method: "DELETE" }),
  );
export const runTeam = (
  organizationId: string,
  teamId: string,
  objective: string,
  threadId?: string,
) =>
  authenticated<TeamRunResult>(
    `/agent-teams/${id(teamId)}/runs`,
    scoped(
      organizationId,
      json("POST", threadId ? { objective, thread_id: threadId } : { objective }),
    ),
  );
export const listTeamRuns = (
  organizationId: string,
  filters: { teamId?: string; status?: TeamRunStatus } = {},
) => {
  const query = new URLSearchParams();
  if (filters.teamId) query.set("team_id", filters.teamId);
  if (filters.status) query.set("status", filters.status);
  const search = query.size ? `?${query}` : "";
  return authenticated<TeamRunSummary[]>(
    `/agent-team-runs${search}`,
    scoped(organizationId),
  );
};
export const getTeamRun = (organizationId: string, runId: string) =>
  authenticated<TeamRunDetail>(
    `/agent-team-runs/${id(runId)}`,
    scoped(organizationId),
  );
