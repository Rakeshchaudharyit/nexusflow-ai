import Link from "next/link";
import { RiskBadge } from "../ui/design-system";
import { StatusPill } from "@/components/agents/status-pill";
import { formatDate } from "@/components/agents/resource";
import {
  actionExecuted,
  actionLabel,
  actionOutcome,
  policyLabel,
  SIMULATION_NOTICE,
} from "@/lib/actions";
import type { RunApproval, TeamAction as Action } from "@/lib/api/teams";

/** The proposed business action of a team run and its policy/approval lifecycle. */
export function TeamAction({
  action,
  approval,
}: {
  action: Action;
  approval?: RunApproval | null;
}) {
  const execution = approval?.execution;
  const approvalId = action.approval_id ?? approval?.approval_id;
  return (
    <div className={`action-panel policy-${action.decision}`}>
      <div className="policy-banner"><span>{policyLabel(action.decision)}</span><RiskBadge risk={action.risk_level}/></div>
      <dl className="details">
        <dt>Action</dt>
        <dd>{actionLabel(action.action_type)}</dd>
        <dt>Policy</dt>
        <dd>
          {policyLabel(action.decision)} ·{" "}
          <span className="mono">{action.rule_key}</span>
        </dd>
        <dt>Risk</dt>
        <dd><RiskBadge risk={action.risk_level}/></dd>
        <dt>Reason</dt>
        <dd>{action.reason}</dd>
        <dt>Outcome</dt>
        <dd>
          <StatusPill status={action.status} /> {actionOutcome(action)}
        </dd>
        {approvalId && (
          <>
            <dt>Approval</dt>
            <dd>
              {approval?.approval_status && (
                <StatusPill status={approval.approval_status} />
              )}{" "}
              <Link href={`/app/approvals/${approvalId}`}>View approval</Link>
            </dd>
          </>
        )}
        {action.message && (
          <>
            <dt>Result</dt>
            <dd>{action.message}</dd>
          </>
        )}
        {execution && (
          <>
            <dt>Executed</dt>
            <dd>
              {formatDate(execution.created_at)} · execution{" "}
              <span className="mono">{execution.id.slice(0, 8)}</span>
            </dd>
          </>
        )}
      </dl>
      {actionExecuted(action.status) ||
      action.action_type === "send_followup_email" ? (
        <p className="notice">{SIMULATION_NOTICE}</p>
      ) : null}
    </div>
  );
}
