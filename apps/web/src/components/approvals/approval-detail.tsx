"use client";

import { LoadingState } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback, useState } from "react";
import { useAuth } from "@/components/auth-provider";
import {
  describeError,
  formatDate,
  usePolling,
  useResource,
} from "@/components/agents/resource";
import { RiskBadge } from "../ui/design-system";
import { StatusPill } from "@/components/agents/status-pill";
import { useWorkspace } from "@/components/workspace-shell";
import {
  actionLabel,
  approvalOutcome,
  awaitingWorker,
  SIMULATION_NOTICE,
} from "@/lib/actions";
import { approveAction, getApproval, rejectAction } from "@/lib/api/approvals";

export function ApprovalDetail({ approvalId }: { approvalId: string }) {
  const organization = useWorkspace();
  const { user } = useAuth();
  const load = useCallback(
    () => getApproval(organization.id, approvalId),
    [organization.id, approvalId],
  );
  const {
    data: approval,
    error,
    notFound,
    loading,
    reload,
  } = useResource(load);
  // After approval the worker runs the action; follow it until the execution is recorded.
  usePolling(!!approval && awaitingWorker(approval), reload);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  // The API enforces this too; the UI only avoids offering controls that would be refused.
  const canReview =
    organization.role === "owner" || organization.role === "admin";

  async function decide(approve: boolean) {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await (approve ? approveAction : rejectAction)(
        organization.id,
        approvalId,
        comment,
      );
    } catch (problem) {
      setFailure(describeError(problem));
    } finally {
      setBusy(false);
      reload();
    }
  }

  if (loading) return <LoadingState />;
  if (notFound || !approval)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Approval not found" : "Could not load this approval"}</h1>
        <p className="muted-text">
          {notFound
            ? `This approval does not exist in ${organization.name}.`
            : error}
        </p>
        <Link href="/app/approvals">Back to approvals</Link>
        {!notFound && (
          <button className="retry-button" onClick={reload}>
            Retry
          </button>
        )}
      </section>
    );
  const pending = approval.status === "pending";
  const reviewer =
    approval.reviewed_by_user_id === user?.id
      ? "You"
      : approval.reviewed_by_user_id;
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">APPROVALS / {organization.name}</p>
          <h1>{actionLabel(approval.action_type)}</h1>
        </div>
        <Link href="/app/approvals">Back to approvals</Link>
      </div>
      <section className={`panel approval-decision decision-${approval.status}`}>
        <div className="decision-banner"><span>{pending ? "Human approval required" : `${approval.status} decision`}</span><RiskBadge risk={approval.risk_level} /></div>
        <div className="approval-grid">
        <dl className="details">
          <dt>Status</dt>
          <dd>
            <StatusPill status={approval.status} />
            {approval.status !== "pending" && ` ${approvalOutcome(approval)}`}
          </dd>
          <dt>Action type</dt>
          <dd className="mono">{approval.action_type}</dd>
          <dt>Risk level</dt>
          <dd><RiskBadge risk={approval.risk_level} /></dd>
          <dt>Policy reason</dt>
          <dd>
            {approval.reason}{" "}
            <span className="mono muted-text">({approval.rule_key})</span>
          </dd>
          <dt>Team</dt>
          <dd>
            {approval.team_name ?? "—"}
            {approval.agent_name && ` · proposed by ${approval.agent_name}`}
          </dd>
          <dt>Objective</dt>
          <dd className="preformatted">{approval.objective ?? "—"}</dd>
          <dt>Team run</dt>
          <dd>
            <Link href={`/app/team-runs/${approval.team_run_id}`}>
              View team run {approval.team_run_id.slice(0, 8)}
            </Link>
          </dd>
          <dt>Created</dt>
          <dd>{formatDate(approval.created_at)}</dd>
          <dt>Expires</dt>
          <dd>{formatDate(approval.expires_at)}</dd>
          {approval.reviewed_at && (
            <>
              <dt>Reviewed</dt>
              <dd>
                {reviewer} · {formatDate(approval.reviewed_at)}
              </dd>
              <dt>Review comment</dt>
              <dd>{approval.review_comment ?? "—"}</dd>
            </>
          )}
        </dl>
        <section className="payload-review"><h2>Proposed action payload</h2>
          {Object.entries(approval.payload).sort(([a],[b]) => { const order = ["recipient", "subject", "body"]; return (order.includes(a) ? order.indexOf(a) : 3) - (order.includes(b) ? order.indexOf(b) : 3); }).map(([key,value]) => <div className={`payload-field payload-${key}`} key={key}><span>{key.replaceAll("_", " ")}</span><p className="preformatted">{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</p></div>)}
          <details className="technical-log"><summary>View raw JSON</summary><pre className="payload">{JSON.stringify(approval.payload, null, 2)}</pre></details>
        </section></div>
        <p className="field-hint">
          The payload is fixed when approval is requested; reviewers cannot edit
          it.
        </p>
        {approval.execution && (
          <div className="action-panel">
            <h2>Execution</h2>
            <dl className="details">
              <dt>Result</dt>
              <dd>
                <StatusPill status={approval.execution.status} />{" "}
                {approval.execution.result.message}
              </dd>
              <dt>Executed</dt>
              <dd>{formatDate(approval.execution.created_at)}</dd>
            </dl>
          </div>
        )}
        <p className="notice">{SIMULATION_NOTICE}</p>
        {failure && (
          <p className="form-error" role="alert">
            {failure}
          </p>
        )}
        {pending && canReview && (
          <div className="review-form">
            <label>
              Review comment (optional)
              <textarea
                value={comment}
                maxLength={1000}
                rows={2}
                onChange={(event) => setComment(event.target.value)}
              />
            </label>
            <div className="button-row">
              <button
                className="primary-button"
                disabled={busy}
                onClick={() => void decide(true)}
              >
                {busy ? "Submitting…" : "Approve & Execute"}
              </button>
              <button disabled={busy} onClick={() => void decide(false)}>
                Reject
              </button>
            </div>
          </div>
        )}
        {pending && !canReview && (
          <p className="muted-text">
            Only workspace owners and admins can approve or reject actions.
          </p>
        )}
      </section>
    </>
  );
}
