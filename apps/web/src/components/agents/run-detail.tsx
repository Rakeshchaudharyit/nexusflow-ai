"use client";

import { LoadingState } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback } from "react";
import { useWorkspace } from "@/components/workspace-shell";
import { getRun, type RunEvent } from "@/lib/api/agents";
import { RunExecution } from "@/components/jobs/run-execution";
import { MemoryUsagePanel } from "@/components/memory/memory-usage";
import { TraceLink } from "@/components/observability/trace-link";
import { CitedText, KnowledgeRetrievalPanel } from "@/components/knowledge/citations";
import { displayStatus, isRunActive } from "@/lib/jobs";
import { formatDate, formatDuration, usePolling, useResource } from "./resource";
import { StatusPill } from "./status-pill";
import { ToolCalls } from "./tool-calls";

const nodeLabels: Record<string, string> = {
  analyze_request: "Analyze request",
  create_plan: "Create plan",
  execute_demo_tool: "Execute tool",
  compose_response: "Compose response",
};

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

function describe(event: RunEvent): string {
  if (event.event_type === "run_started")
    return event.attempt && event.attempt > 1
      ? `Run started · attempt ${event.attempt}`
      : "Run started";
  if (event.event_type === "retry_scheduled")
    return `Attempt ${event.attempt ?? ""} failed temporarily · retry scheduled`;
  if (event.event_type === "run_cancelled") return "Run cancelled";
  if (event.event_type === "memory_saved" || event.event_type === "memory_updated")
    return `Thread memory ${memoryChanges(event)}`;
  if (event.event_type === "run_completed") return "Run completed";
  if (event.event_type === "run_failed") return "Run failed";
  if (!event.node_name) return event.event_type.replaceAll("_", " ");
  const node = nodeLabels[event.node_name ?? ""] ?? event.node_name;
  const phase = {
    started: "started",
    completed: "completed",
    failed: "failed",
  };
  return `${node} ${phase[event.status]}`;
}

function toolNames(event: RunEvent): string | null {
  const results = event.output_payload?.tool_results;
  if (!Array.isArray(results)) return null;
  return results
    .map((item) =>
      typeof item === "object" && item && "tool" in item
        ? String(item.tool)
        : "",
    )
    .filter(Boolean)
    .join(", ");
}

export function RunDetail({ runId }: { runId: string }) {
  const organization = useWorkspace();
  const load = useCallback(
    () => getRun(organization.id, runId),
    [organization.id, runId],
  );
  const { data: run, error, notFound, loading, reload } =
    useResource(load);
  // Follow the worker until the run settles (bounded 2 s polling, no WebSockets).
  usePolling(!!run && isRunActive(run.status), reload);
  if (loading) return <LoadingState />;
  if (notFound || !run)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Run not found" : "Could not load this run"}</h1>
        <p className="muted-text">
          {notFound
            ? `This run does not exist in ${organization.name}.`
            : error}
        </p>
        <Link href="/app/runs">Back to runs</Link>
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
          <p className="eyebrow">RUNS / {organization.name}</p>
          <h1 className="mono-heading">Run {run.id.slice(0, 8)}</h1>
        </div>
        <Link href="/app/runs">Back to runs</Link>
      </div>
      <section className="panel">
        <dl className="details">
          <dt>Status</dt>
          <dd>
            <StatusPill status={displayStatus(run.status, run.execution_status)} />
          </dd>
          <dt>Agent</dt>
          <dd>
            <Link href={`/app/agents/${run.agent_id}`}>{run.agent_name}</Link>
          </dd>
          <dt>Input</dt>
          <dd className="preformatted">{run.input_text}</dd>
          <dt>{run.error ? "Error" : "Output"}</dt>
          <dd className="cited-text">
            {run.error ? (
              `${run.error.message} (${run.error.code})`
            ) : run.final_output?.summary ? (
              <CitedText
                text={run.final_output.summary}
                citations={run.final_output.citations ?? []}
              />
            ) : (
              "—"
            )}
          </dd>
          <dt>Intent</dt>
          <dd className="mono">
            {run.final_output?.intent ?? String(run.state?.intent ?? "—")}
          </dd>
          <dt>Provider</dt>
          <dd className="mono">{run.final_output?.provider ?? "—"}</dd>
          <dt>Started</dt>
          <dd>{formatDate(run.started_at)}</dd>
          <dt>Completed</dt>
          <dd>{formatDate(run.completed_at)}</dd>
          <dt>Duration</dt>
          <dd>
            {formatDuration(run.duration_ms)} · {run.step_count} steps
          </dd>
        </dl>
      </section>
      <MemoryUsagePanel threadId={run.thread_id} usage={run.memory_context} />
      <TraceLink runId={run.id} version={run.status} />
      <KnowledgeRetrievalPanel
        retrieval={run.knowledge}
        citations={run.final_output?.citations ?? []}
      />
      <RunExecution
        kind="agent"
        runId={run.id}
        status={run.status}
        createdBy={run.created_by_user_id}
        execution={run.execution}
        onChanged={reload}
      />
      <section className="panel"><h2>Execution trace</h2><ol className="execution-trace">{run.events.filter(event => (event.node_name && event.status !== "started") || event.event_type === "retry_scheduled" || event.event_type === "run_cancelled").map(event => <li className={`execution-step step-${event.status}`} key={event.id}><span className="execution-dot" aria-hidden="true">{event.status === "failed" ? "!" : "✓"}</span><div><h3>{describe(event)}</h3>{toolNames(event) && <p className="mono muted-text">{toolNames(event)}</p>}{event.error_message && <p className="form-error">{event.error_message}</p>}</div><span className="mono muted-text">{formatDuration(event.duration_ms)}</span></li>)}</ol></section>
      <section className="panel">
        <h2>Tool calls</h2>
        <ToolCalls calls={run.tool_calls} />
      </section>
      <section className="panel">
        <details className="technical-log"><summary>Technical event log · {run.events.length} events</summary>
        <ol className="timeline">
          {run.events.map((event) => (
            <li key={event.id} className={`timeline-${event.status}`}>
              <span className="mono">
                {String(event.sequence).padStart(2, "0")}
              </span>
              <span>
                {describe(event)}
                {toolNames(event) && (
                  <span className="muted-text"> · {toolNames(event)}</span>
                )}
                {event.error_message && (
                  <span className="timeline-error">
                    {" "}
                    · {event.error_message}
                  </span>
                )}
              </span>
              <span className="muted-text nowrap">
                {event.duration_ms === null
                  ? ""
                  : formatDuration(event.duration_ms)}
              </span>
            </li>
          ))}
        </ol></details>
      </section>
    </>
  );
}
