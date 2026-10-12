"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { formatDate, usePolling, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { LoadingState, PageHeader } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import {
  getObservabilitySummary,
  listTraces,
  type ObservabilitySummary,
  type TraceFilters,
} from "@/lib/api/observability";
import type { TeamRunStatus } from "@/lib/api/teams";
import { isRunActive } from "@/lib/jobs";
import { formatMs } from "@/lib/observability";

const WINDOWS = { "24h": 24, "7d": 168, "30d": 720 } as const;

function SummaryStrip({ summary }: { summary: ObservabilitySummary }) {
  const failedShare = summary.runs ? Math.round((summary.failed / summary.runs) * 100) : 0;
  return (
    <>
      <nav className="operations-strip observe-strip" aria-label="Run health">
        <div>
          <span>RUNS</span>
          <strong>{String(summary.runs).padStart(2, "0")}</strong>
          <small>
            {summary.completed} completed · {summary.failed} failed
            {summary.runs ? ` (${failedShare}%)` : ""}
          </small>
        </div>
        <div>
          <span>LATENCY</span>
          <strong className="mono">{formatMs(summary.avg_duration_ms)}</strong>
          <small>avg completed run · max {formatMs(summary.max_duration_ms)}</small>
        </div>
        <div>
          <span>QUEUE WAIT</span>
          <strong className="mono">{formatMs(summary.avg_queue_wait_ms)}</strong>
          <small>avg job → worker claim</small>
        </div>
        <div>
          <span>RETRIES</span>
          <strong>{String(summary.retries).padStart(2, "0")}</strong>
          <small>{summary.runs_with_retries} runs retried</small>
        </div>
        <div>
          <span>KNOWLEDGE</span>
          <strong>{String(summary.knowledge_searches).padStart(2, "0")}</strong>
          <small>
            searches · {summary.knowledge_no_match} no-match
            {summary.knowledge_avg_results !== null
              ? ` · ${summary.knowledge_avg_results} avg results`
              : ""}
          </small>
        </div>
      </nav>
      <div className="observe-grid">
        <section className="panel">
          <h2>Errors by category</h2>
          {summary.errors_by_category.length === 0 ? (
            <p className="muted-text">No failed runs in this window.</p>
          ) : (
            <ul className="metric-bars">
              {summary.errors_by_category.map((item) => (
                <li key={item.key}>
                  <span className="mono">{item.key}</span>
                  <span className="metric-bar" aria-hidden="true">
                    <i style={{ width: `${(item.count / summary.failed) * 100}%` }} />
                  </span>
                  <strong>{item.count}</strong>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="panel">
          <h2>Tool usage</h2>
          {summary.tool_usage.length === 0 ? (
            <p className="muted-text">No tool calls in this window.</p>
          ) : (
            <ul className="metric-bars">
              {summary.tool_usage.slice(0, 6).map((item) => (
                <li key={item.key}>
                  <span className="mono">{item.key}</span>
                  <span className="metric-bar" aria-hidden="true">
                    <i style={{ width: `${(item.count / summary.tool_usage[0].count) * 100}%` }} />
                  </span>
                  <strong>
                    {item.count}
                    {item.failures ? <em> · {item.failures} failed</em> : null}
                  </strong>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="panel">
          <h2>Approvals</h2>
          {Object.keys(summary.approvals).length === 0 ? (
            <p className="muted-text">No approval requests in this window.</p>
          ) : (
            <dl className="details compact">
              {Object.entries(summary.approvals).map(([status, count]) => (
                <div key={status} className="detail-pair">
                  <dt>{status}</dt>
                  <dd className="mono">{count}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      </div>
    </>
  );
}

export function TraceList() {
  const organization = useWorkspace();
  const [filters, setFilters] = useState<TraceFilters>({ origin: "user" });
  const [period, setPeriod] = useState<keyof typeof WINDOWS>("24h");
  const loadTraces = useCallback(
    () => listTraces(organization.id, { ...filters, limit: 50 }),
    [organization.id, filters],
  );
  const loadSummary = useCallback(
    () => getObservabilitySummary(organization.id, WINDOWS[period]),
    [organization.id, period],
  );
  const traces = useResource(loadTraces);
  const summary = useResource(loadSummary);
  usePolling(!!traces.data?.some((trace) => isRunActive(trace.status)), traces.reload);
  const set = (key: keyof TraceFilters, value: string) =>
    setFilters((current) => ({ ...current, [key]: value || undefined }));
  return (
    <>
      <PageHeader
        eyebrow={`OBSERVE / ${organization.name}`}
        title="Traces"
        description="Every agent and team run as a timed span tree: worker attempts, graph nodes, agents, tools, MCP, memory, knowledge, policy and approvals. All values are measured, never estimated."
      />
      <div className="filter-row" role="group" aria-label="Summary window">
        {(Object.keys(WINDOWS) as (keyof typeof WINDOWS)[]).map((key) => (
          <button
            key={key}
            className={key === period ? "primary-button" : ""}
            aria-pressed={key === period}
            onClick={() => setPeriod(key)}
          >
            Last {key}
          </button>
        ))}
      </div>
      {summary.data && <SummaryStrip summary={summary.data} />}
      <section className="panel">
        <div className="filter-row">
          <label>
            Run type
            <select value={filters.run_type ?? ""} onChange={(e) => set("run_type", e.target.value)}>
              <option value="">All</option>
              <option value="agent">Agent</option>
              <option value="team">Team</option>
            </select>
          </label>
          <label>
            Status
            <select value={filters.status ?? ""} onChange={(e) => set("status", e.target.value)}>
              <option value="">All</option>
              {["completed", "failed", "awaiting_approval", "running", "queued", "cancelled"].map(
                (status) => (
                  <option key={status} value={status}>
                    {status.replace("_", " ")}
                  </option>
                ),
              )}
            </select>
          </label>
          <label>
            Since
            <input
              type="date"
              value={filters.since?.slice(0, 10) ?? ""}
              onChange={(e) =>
                set("since", e.target.value ? new Date(e.target.value).toISOString() : "")
              }
            />
          </label>
          <label>
            Origin
            <select value={filters.origin ?? "user"} onChange={(e) => set("origin", e.target.value)}>
              <option value="user">User runs</option>
              <option value="evaluation">Evaluation runs</option>
              <option value="all">All</option>
            </select>
          </label>
        </div>
        {traces.error && <p className="form-error" role="alert">{traces.error}</p>}
        {traces.loading && <LoadingState />}
        {traces.data && traces.data.length === 0 && (
          <p className="muted-text">
            No traces match. Every agent or team run started since M10 is traced.
          </p>
        )}
        {traces.data && traces.data.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Trace</th>
                  <th>Type</th>
                  <th>Agent / team</th>
                  <th>Status</th>
                  <th>Duration</th>
                  <th>Queue wait</th>
                  <th>Attempts</th>
                  <th>Started</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {traces.data.map((trace) => (
                  <tr key={trace.id}>
                    <td className="mono">
                      <Link href={`/app/traces/${trace.id}`}>{trace.id.slice(0, 8)}</Link>
                      {trace.origin === "evaluation" && <span className="memory-chip"> eval</span>}
                    </td>
                    <td className="mono">{trace.run_type}</td>
                    <td>{trace.target_name ?? "—"}</td>
                    <td><StatusPill status={trace.status as TeamRunStatus} /></td>
                    <td className="mono nowrap">{formatMs(trace.duration_ms)}</td>
                    <td className="mono nowrap">{formatMs(trace.queue_wait_ms)}</td>
                    <td className="mono">
                      {trace.attempt_count}
                      {trace.retry_count ? ` · ${trace.retry_count} retry` : ""}
                    </td>
                    <td className="nowrap">{formatDate(trace.started_at ?? trace.created_at)}</td>
                    <td className="mono">
                      {trace.error_code ? `${trace.error_category} · ${trace.error_code}` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
