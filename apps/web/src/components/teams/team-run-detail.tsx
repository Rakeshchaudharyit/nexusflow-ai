"use client";

import { LoadingState } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback } from "react";
import {
  formatDate,
  formatDuration,
  usePolling,
  useResource,
} from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { RunExecution } from "@/components/jobs/run-execution";
import { MemoryUsagePanel } from "@/components/memory/memory-usage";
import { TraceLink } from "@/components/observability/trace-link";
import { useWorkspace } from "@/components/workspace-shell";
import { actionLabel } from "@/lib/actions";
import { displayStatus, isRunActive } from "@/lib/jobs";
import { getTeamRun, hasAnalysis, type TeamRunEvent } from "@/lib/api/teams";
import { KeyValues } from "./key-values";
import { roleLabel } from "./roles";
import { TeamAction } from "./team-action";
import { TeamOutputView } from "./team-output";

function memoryChanges(event: { output_payload: Record<string, unknown> | null }): string {
  const payload = event.output_payload ?? {};
  const names = (key: string) =>
    Array.isArray(payload[key]) ? (payload[key] as unknown[]).map(String) : [];
  const saved = names("saved");
  const updated = names("updated");
  return [
    saved.length ? `saved ${saved.join(", ")}` : "",
    updated.length ? `updated ${updated.join(", ")}` : "",
  ]
    .filter(Boolean)
    .join("; ");
}

function describe(event: TeamRunEvent): string {
  const role = roleLabel(event.agent_role);
  const output = event.output_payload ?? {};
  const action = actionLabel(
    String(output.action_type ?? event.input_payload?.action_type ?? ""),
  );
  switch (event.event_type) {
    case "action_proposed":
      return `Supervisor proposed action: ${action}`;
    case "policy_allowed":
      return `Policy allowed ${action} automatically`;
    case "policy_denied":
      return `Policy denied ${action}: ${event.error_message ?? ""}`;
    case "approval_requested":
      return `Human approval requested for ${action}`;
    case "approval_approved":
      return "Human reviewer approved the action";
    case "approval_rejected":
      return "Human reviewer rejected the action";
    case "approval_expired":
      return "Approval expired without a decision";
    case "action_started":
      return `Simulated action started: ${action}`;
    case "action_completed":
      return `Simulated action completed: ${String(output.message ?? "")}`;
    case "action_failed":
      return `Simulated action failed: ${event.error_message ?? ""}`;
    case "team_run_started":
      return event.attempt && event.attempt > 1
        ? `Team run started · attempt ${event.attempt}`
        : "Team run started";
    case "retry_scheduled":
      return `Attempt ${event.attempt ?? ""} failed temporarily · retry scheduled: ${
        event.error_message ?? ""
      }`;
    case "team_run_cancelled":
      return "Team run cancelled";
    case "memory_saved":
    case "memory_updated":
      return `Thread memory ${memoryChanges(event)}`;
    case "supervisor_plan_created":
      return "Supervisor planned the work";
    case "handoff_started":
      return `Supervisor → ${role}: ${String(event.input_payload?.task ?? "")}`;
    case "agent_completed":
      return `${role} completed → Supervisor`;
    case "agent_failed":
      return `${role} failed: ${event.error_message ?? ""}`;
    case "validation_failed":
      return "Validator rejected the draft";
    case "revision_requested":
      return "Supervisor requested a revision";
    case "team_run_completed":
      return "Team run completed";
    case "team_run_failed":
      return `Team run failed: ${event.error_message ?? ""}`;
  }
}

export function TeamRunDetail({ runId }: { runId: string }) {
  const organization = useWorkspace();
  const load = useCallback(
    () => getTeamRun(organization.id, runId),
    [organization.id, runId],
  );
  const { data: run, error, notFound, loading, reload } =
    useResource(load);
  // Follow the worker until the run settles or pauses for approval (bounded polling).
  usePolling(!!run && isRunActive(run.status), reload);
  if (loading) return <LoadingState />;
  if (notFound || !run)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Team run not found" : "Could not load this team run"}</h1>
        <p className="muted-text">
          {notFound
            ? `This team run does not exist in ${organization.name}.`
            : error}
        </p>
        <Link href="/app/team-runs">Back to team runs</Link>
        {!notFound && (
          <button className="retry-button" onClick={reload}>
            Retry
          </button>
        )}
      </section>
    );
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">TEAM RUNS / {organization.name}</p>
          <h1>{run.team_name}</h1>
          <p className="page-description mono">Run {run.id.slice(0, 8)}</p>
        </div>
        <Link href="/app/team-runs">Back to team runs</Link>
      </div>
      <section className="panel run-summary">
        <dl className="details">
          <dt>Status</dt>
          <dd>
            <StatusPill status={displayStatus(run.status, run.execution_status)} />
          </dd>
          <dt>Team</dt>
          <dd>
            <Link href={`/app/teams/${run.team_id}`}>{run.team_name}</Link>
          </dd>
          <dt>Objective</dt>
          <dd className="preformatted">{run.objective}</dd>
          {run.error && (
            <>
              <dt>Error</dt>
              <dd>
                {run.error.message} ({run.error.code})
              </dd>
            </>
          )}
          <dt>Started</dt>
          <dd>{formatDate(run.started_at)}</dd>
          <dt>Completed</dt>
          <dd>{formatDate(run.completed_at)}</dd>
          <dt>Duration</dt>
          <dd>
            {formatDuration(run.duration_ms)} · {run.step_count} agent steps ·{" "}
            {run.revisions} revisions
          </dd>
        </dl>
      </section>
      <MemoryUsagePanel threadId={run.thread_id} usage={run.memory_context} />
      <TraceLink runId={run.id} version={run.status} />
      <RunExecution
        kind="team"
        runId={run.id}
        status={run.status}
        createdBy={run.created_by_user_id}
        execution={run.execution}
        onChanged={reload}
      />
      <div className="run-detail-grid">
      <section className="panel execution-panel">
        <div className="section-heading"><h2>Execution trace</h2><span>{run.results.length} AGENT RESULTS</span></div>
        <div className="trace-columns mono"><span>STEP</span><span>ACTOR / ACTION / RESULT</span><span>TIME</span></div><ol className="execution-trace">
          {run.plan.length > 0 && <li className="execution-step"><span className="execution-dot" aria-hidden="true">↳</span><div><span className="eyebrow">Supervisor</span><h3>Created execution plan</h3><p className="muted-text">{run.plan.length} planned steps · shared context across specialist handoffs</p></div></li>}
          {run.results.map((result,index) => <li key={`${result.agent_id}-${index}`} className={`execution-step step-${result.status}`}>
            <span className="execution-dot" aria-hidden="true">{String(index+1).padStart(2,"0")}</span>
            <div><span className="eyebrow">Supervisor → {roleLabel(result.role)}</span><h3>{result.agent_name ?? roleLabel(result.role)}</h3>
              {result.tool_calls.map((call,callIndex) => <p className="trace-tool mono" key={callIndex}>{String(call.tool_type ?? (String(call.tool_key).startsWith("mcp:") ? "MCP" : "Internal"))} · {String(call.tool_key ?? call.tool_name ?? "Tool invocation")}{call.duration_ms != null && ` · ${formatDuration(Number(call.duration_ms))}`}</p>)}
              {typeof (result.output?.summary ?? result.output?.executive_summary) === "string" && <p className="trace-summary muted-text">{String(result.output?.summary ?? result.output?.executive_summary)}</p>}{Array.isArray(result.output?.signals) && <p className="trace-summary muted-text">{result.output.signals.filter((signal: unknown)=>typeof signal === "string").join(" · ")}</p>}
              {result.error ? <p className="form-error">{result.error.message}</p> : <span className="trace-result muted-text">{typeof result.output?.opportunity_score === "number" ? `Opportunity score · ${result.output.opportunity_score} / 100` : typeof result.output?.confidence === "number" ? `Validation confidence · ${Math.round(result.output.confidence * 100)}%` : ""}</span>}
            </div><span className="mono muted-text">{formatDuration(result.duration_ms)}</span>
          </li>)}
          {run.events.filter(event => ["validation_failed", "revision_requested", "policy_allowed", "policy_denied", "approval_requested", "approval_approved", "approval_rejected", "approval_expired", "action_completed", "action_failed"].includes(event.event_type)).map(event => <li key={event.id} className={`execution-step step-${event.status}`}><span className="execution-dot" aria-hidden="true">{event.status === "failed" ? "!" : "↳"}</span><div><span className="eyebrow">Policy / human oversight</span><h3>{describe(event)}</h3></div><span className="mono muted-text">{formatDuration(event.duration_ms)}</span></li>)}
        </ol>
      </section>
      <div className="run-detail-side">
      {run.action && (
        <section className="panel">
          <h2>Business action</h2>
          <TeamAction action={run.action} approval={run.approval} />
        </section>
      )}
      {hasAnalysis(run.final_output) && (
        <section className="panel">
          <h2>Final result</h2>
          <TeamOutputView output={run.final_output} />
        </section>
      )}
      </div></div>
      <section className="panel">
        <details className="technical-log"><summary>Supervisor plan · {run.plan.length} steps</summary>
        {run.plan.length ? (
          <ol className="plain-list">
            {run.plan.map((step) => (
              <li key={step.step}>
                <strong>{roleLabel(step.role)}</strong> · {step.agent_name} —{" "}
                {step.task}
              </li>
            ))}
          </ol>
        ) : (
          <p className="muted-text">No plan was created.</p>
        )}</details>
      </section>
      <section className="panel">
        <details className="technical-log"><summary>Structured agent results</summary>
        {run.results.length === 0 && (
          <p className="muted-text">No agent completed work.</p>
        )}
        {run.results.map((result, index) => (
          <div key={index} className="agent-result">
            <h3>
              {roleLabel(result.role)} · {result.agent_name ?? "agent"}{" "}
              <StatusPill
                status={result.status === "completed" ? "completed" : "failed"}
              />{" "}
              <span className="muted-text">
                {formatDuration(result.duration_ms)}
              </span>
            </h3>
            {result.error ? (
              <p className="form-error">
                {result.error.message} ({result.error.code})
              </p>
            ) : (
              <KeyValues value={result.output} />
            )}
            {result.tool_calls.length > 0 && (
              <p className="muted-text mono">
                Tools:{" "}
                {result.tool_calls
                  .map(
                    (call) =>
                      `${String(call.tool_key ?? call.tool_name)}${call.server_name ? ` via ${String(call.server_name)}` : ""}`,
                  )
                  .join(", ")}
              </p>
            )}
          </div>
        ))}</details>
      </section>
      <section className="panel">
        <details className="technical-log"><summary>Handoff context</summary>
        <ol className="plain-list">
          {run.handoffs.map((handoff) => (
            <li key={handoff.sequence}>
              Supervisor → {roleLabel(handoff.to_role)} ({handoff.agent_name}):
              shared{" "}
              <span className="mono">
                {Object.keys(handoff.context).join(", ")}
              </span>
            </li>
          ))}
        </ol></details>
      </section>
      <section className="panel">
        <details className="technical-log"><summary>Technical event log · {run.events.length} events</summary>
        <ol className="timeline">
          {run.events.map((event) => (
            <li key={event.id} className={`timeline-${event.status}`}>
              <span className="mono">
                {String(event.sequence).padStart(2, "0")}
              </span>
              <span>{describe(event)}</span>
              <span className="muted-text nowrap">
                {event.duration_ms === null
                  ? ""
                  : formatDuration(event.duration_ms)}
              </span>
            </li>
          ))}
        </ol>
        </details>
      </section>
    </>
  );
}
