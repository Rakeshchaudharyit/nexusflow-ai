import type {
  ActionDecision,
  ActionStatus,
  ApprovalStatus,
  TeamAction,
  TeamRunStatus,
} from "./api/teams";

/** Shown wherever an action result appears: every M6 action is a local simulation. */
export const SIMULATION_NOTICE =
  "Simulation only: no real email was sent and no external CRM or system was changed.";

const ACTION_LABELS: Record<string, string> = {
  send_followup_email: "Send follow-up email",
  create_crm_note: "Create CRM note",
  update_opportunity_stage: "Update opportunity stage",
  delete_record: "Delete record",
};
const POLICY_LABELS: Record<ActionDecision, string> = {
  allow: "Allowed automatically",
  require_approval: "Human approval required",
  deny: "Denied",
};

export const actionLabel = (actionType: string) =>
  ACTION_LABELS[actionType] ?? actionType.replaceAll("_", " ");
export const policyLabel = (decision: ActionDecision) =>
  POLICY_LABELS[decision];

/** One-line outcome that reflects the backend's action status, never an assumed one. */
export function actionOutcome(
  action: Pick<TeamAction, "action_type" | "status">,
): string {
  const label = actionLabel(action.action_type).toLowerCase();
  const outcomes: Record<ActionStatus, string> = {
    awaiting_approval: `Awaiting human approval. The action to ${label} has not run.`,
    completed: `Simulated action executed: ${label}.`,
    failed: `The simulated action to ${label} failed. It was not retried.`,
    rejected: "Approval rejected. The action was not executed.",
    denied: "Denied by policy. The action was not executed.",
    expired: "The approval expired. The action was not executed.",
  };
  return outcomes[action.status];
}

export const actionExecuted = (status: ActionStatus) =>
  status === "completed" || status === "failed";

type ApprovalOutcomeInput = {
  status: ApprovalStatus;
  execution: unknown | null;
  team_run_status: TeamRunStatus | null;
};

/** Outcome sentence for a decided approval. Since M7 the approved action runs in the
 * worker, so "approved" is only "ran" once an execution exists. */
export function approvalOutcome(approval: ApprovalOutcomeInput): string | null {
  switch (approval.status) {
    case "pending":
      return null;
    case "rejected":
      return "Rejected. The action was not executed.";
    case "expired":
      return "Expired before review. The action was not executed.";
    case "cancelled":
      return "Cancelled with its team run. The action was not executed.";
    case "approved":
      if (approval.execution) return "Approved. The simulated action ran once.";
      if (
        approval.team_run_status === "queued" ||
        approval.team_run_status === "running"
      )
        return "Approved. The simulated action is queued for the worker.";
      if (approval.team_run_status === "cancelled")
        return "Approved, but the team run was cancelled before the action ran.";
      return "Approved. The action did not run.";
  }
}

/** Keep polling an approval while its approved action waits for the worker. */
export const awaitingWorker = (approval: ApprovalOutcomeInput) =>
  approval.status === "approved" &&
  !approval.execution &&
  (approval.team_run_status === "queued" ||
    approval.team_run_status === "running");
