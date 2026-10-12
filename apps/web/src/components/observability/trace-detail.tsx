"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { formatDate, usePolling, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { LoadingState } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import { getTrace, type Span, type TraceDetail as Trace } from "@/lib/api/observability";
import type { TeamRunStatus } from "@/lib/api/teams";
import { isRunActive } from "@/lib/jobs";
import {
  SPAN_LABELS,
  bar,
  buildTree,
  formatMs,
  metadataEntries,
  visibleRows,
} from "@/lib/observability";

function SpanDetail({ span }: { span: Span }) {
  return (
    <section className="panel span-detail" aria-live="polite">
      <h2>
        <span className={`span-type span-${span.span_type}`}>{SPAN_LABELS[span.span_type]}</span>{" "}
        {span.name}
      </h2>
      <dl className="details">
        <dt>Status</dt>
        <dd><StatusPill status={span.status as TeamRunStatus} /></dd>
        <dt>Duration</dt>
        <dd className="mono">
          {formatMs(span.duration_ms)} · starts at +{formatMs(span.offset_ms)}
        </dd>
        {span.attempt !== null && (
          <>
            <dt>Attempt</dt>
            <dd className="mono">{span.attempt}</dd>
          </>
        )}
        {span.tool_key && (
          <>
            <dt>Tool</dt>
            <dd className="mono">{span.tool_key}</dd>
          </>
        )}
        {span.input_summary && (
          <>
            <dt>Input</dt>
            <dd className="mono">{span.input_summary}</dd>
          </>
        )}
        {span.output_summary && (
          <>
            <dt>Output</dt>
            <dd className="mono">{span.output_summary}</dd>
          </>
        )}
        {span.error_code && (
          <>
            <dt>Error</dt>
            <dd>
              <span className="form-error">{span.error_message ?? "Failed"}</span>{" "}
              <span className="mono muted-text">
                ({span.error_category} · {span.error_code})
              </span>
            </dd>
          </>
        )}
        {metadataEntries(span.metadata).map(([key, value]) => (
          <div key={key} className="detail-pair">
            <dt>{key}</dt>
            <dd className="mono">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Waterfall({ trace }: { trace: Trace }) {
  const rows = useMemo(() => buildTree(trace.spans), [trace.spans]);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(trace.failing_spans[0] ?? null);
  const shown = visibleRows(rows, collapsed);
  const failing = new Set(trace.failing_spans);
  const chosen = trace.spans.find((span) => span.id === selected);
  const toggle = (id: string) =>
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  if (!trace.spans.length)
    return (
      <section className="panel">
        <h2>Span tree</h2>
        <p className="muted-text">
          {isRunActive(trace.status)
            ? "Waiting for a worker. Spans are recorded when an attempt finishes."
            : "No spans were recorded for this run."}
        </p>
      </section>
    );
  return (
    <>
      <section className="panel">
        <div className="section-caption">
          <h2>Span tree · waterfall</h2>
          <span className="mono muted-text">
            {trace.spans.length} spans · window {formatMs(trace.total_ms)}
          </span>
        </div>
        <div className="waterfall" role="tree" aria-label="Trace spans">
          <div className="waterfall-scale" aria-hidden="true">
            <span>0 ms</span>
            <span>{formatMs(trace.total_ms / 2)}</span>
            <span>{formatMs(trace.total_ms)}</span>
          </div>
          {shown.map(({ span, depth, hasChildren }) => {
            const geometry = bar(span, trace.total_ms);
            return (
              <div
                key={span.id}
                role="treeitem"
                aria-level={depth + 1}
                aria-expanded={hasChildren ? !collapsed.has(span.id) : undefined}
                aria-selected={selected === span.id}
                className={`waterfall-row status-row-${span.status}${
                  selected === span.id ? " selected" : ""
                }${failing.has(span.id) ? " failing" : ""}`}
              >
                <div className="waterfall-name" style={{ paddingLeft: `${depth * 16}px` }}>
                  {hasChildren ? (
                    <button
                      className="tree-toggle"
                      aria-label={`${collapsed.has(span.id) ? "Expand" : "Collapse"} ${span.name}`}
                      onClick={() => toggle(span.id)}
                    >
                      {collapsed.has(span.id) ? "▸" : "▾"}
                    </button>
                  ) : (
                    <span className="tree-leaf" aria-hidden="true">
                      {depth ? "└" : "·"}
                    </span>
                  )}
                  <button className="span-select" onClick={() => setSelected(span.id)}>
                    <span className={`span-type span-${span.span_type}`}>
                      {SPAN_LABELS[span.span_type]}
                    </span>
                    <span className="span-name" title={span.name}>{span.name}</span>
                  </button>
                </div>
                <span className="waterfall-duration mono">{formatMs(span.duration_ms)}</span>
                <div className="waterfall-track" aria-hidden="true">
                  <i
                    className={`span-bar span-${span.span_type}`}
                    style={{ left: `${geometry.left}%`, width: `${geometry.width}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
        <p className="field-hint">
          Durations are monotonic-clock measurements; bars have a minimum width so sub-millisecond
          steps stay visible. Select a span for its metadata.
        </p>
      </section>
      {chosen && <SpanDetail span={chosen} />}
    </>
  );
}

export function TraceDetail({ traceId }: { traceId: string }) {
  const organization = useWorkspace();
  const load = useCallback(() => getTrace(organization.id, traceId), [organization.id, traceId]);
  const { data: trace, error, notFound, loading, reload } = useResource(load);
  usePolling(!!trace && (isRunActive(trace.status) || trace.status === "awaiting_approval"), reload);
  if (loading) return <LoadingState />;
  if (notFound || !trace)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Trace not found" : "Could not load this trace"}</h1>
        <p className="muted-text">
          {notFound ? `This trace does not exist in ${organization.name}.` : error}
        </p>
        <Link href="/app/traces">Back to traces</Link>
      </section>
    );
  const runHref =
    trace.run_type === "agent" ? `/app/runs/${trace.run_id}` : `/app/team-runs/${trace.run_id}`;
  const failing = trace.spans.filter((span) => trace.failing_spans.includes(span.id));
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">OBSERVE / TRACES / {organization.name}</p>
          <h1 className="mono-heading">Trace {trace.id.slice(0, 8)}</h1>
          <p className="page-description">{trace.run_label}</p>
        </div>
        <Link href="/app/traces">Back to traces</Link>
      </div>
      <section className="panel">
        <dl className="details">
          <dt>Status</dt>
          <dd><StatusPill status={trace.status as TeamRunStatus} /></dd>
          <dt>Run</dt>
          <dd>
            <Link href={runHref}>
              {trace.run_type} run {trace.run_id.slice(0, 8)}
            </Link>{" "}
            · {trace.target_name}
            {trace.origin === "evaluation" && trace.evaluation_run_id && (
              <>
                {" · "}
                <Link href={`/app/evaluations/runs/${trace.evaluation_run_id}`}>evaluation</Link>
              </>
            )}
          </dd>
          <dt>Duration</dt>
          <dd className="mono">
            {formatMs(trace.duration_ms)} run · {formatMs(trace.total_ms)} span window
          </dd>
          <dt>Queue wait</dt>
          <dd className="mono">{formatMs(trace.queue_wait_ms)} (job created → worker claim)</dd>
          <dt>Attempts</dt>
          <dd className="mono">
            {trace.attempt_count} · {trace.retry_count} retries
          </dd>
          {trace.thread_id && trace.origin === "user" && (
            <>
              <dt>Thread</dt>
              <dd><Link href={`/app/threads/${trace.thread_id}`}>View thread memory</Link></dd>
            </>
          )}
          <dt>Started</dt>
          <dd>{formatDate(trace.started_at)}</dd>
          <dt>Completed</dt>
          <dd>{formatDate(trace.completed_at)}</dd>
        </dl>
      </section>
      {trace.error_code && (
        <section className="panel error-panel">
          <h2>Failure</h2>
          <dl className="details">
            <dt>Category</dt>
            <dd className="mono">{trace.error_category}</dd>
            <dt>Error</dt>
            <dd>
              {trace.error_message} <span className="mono muted-text">({trace.error_code})</span>
            </dd>
            <dt>Failing spans</dt>
            <dd>
              {failing.length
                ? failing
                    .map((span) => `${span.name}${span.attempt ? ` (attempt ${span.attempt})` : ""}`)
                    .join(" · ")
                : "—"}
            </dd>
          </dl>
        </section>
      )}
      <Waterfall key={`${trace.id}:${trace.spans.length}`} trace={trace} />
      <section className="panel">
        <h2>Worker jobs</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Job</th>
                <th>Type</th>
                <th>Status</th>
                <th>Attempt</th>
                <th>Worker</th>
                <th>Created</th>
                <th>Last attempt</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {trace.jobs.map((job) => (
                <tr key={job.id}>
                  <td className="mono">{job.id.slice(0, 8)}</td>
                  <td className="mono">{job.job_type}</td>
                  <td><StatusPill status={job.status as TeamRunStatus} /></td>
                  <td className="mono">
                    {job.attempt} / {job.max_attempts}
                  </td>
                  <td className="mono">{job.worker_id ?? "—"}</td>
                  <td className="nowrap">{formatDate(job.created_at)}</td>
                  <td className="mono nowrap">{formatMs(job.execution_ms)}</td>
                  <td className="mono">
                    {job.error_code ? `${job.error_category} · ${job.error_code}` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="field-hint">
          Token usage and cost are not shown: the deterministic provider reports neither, and
          NexusFlow does not estimate them.
        </p>
      </section>
    </>
  );
}
