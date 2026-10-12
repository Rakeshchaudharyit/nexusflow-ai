"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { describeError, formatDate, usePolling, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { LoadingState } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import {
  cancelEvaluation,
  getEvaluationRun,
  listEvaluationRuns,
  setBaseline,
  type EvaluationResult,
} from "@/lib/api/evaluation";
import { expectationLines } from "@/lib/evaluation";
import { formatMs, percent } from "@/lib/observability";

function show(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function RagEvidence({ result }: { result: EvaluationResult }) {
  const retrieval = result.actual.retrieval;
  const expected = (result.expected.citation_documents as string[] | undefined) ?? [];
  if (!retrieval && !expected.length) return null;
  return (
    <div className="rag-evidence">
      <p className="mono">
        Hit@{retrieval?.k ?? "—"}:{" "}
        <strong className={retrieval?.hit_at_k ? "pass-text" : "fail-text"}>
          {retrieval?.hit_at_k ? "hit" : "miss"}
        </strong>{" "}
        · first expected document at rank {retrieval?.rank ?? "—"} · reciprocal rank{" "}
        {retrieval ? retrieval.reciprocal_rank.toFixed(2) : "—"}
      </p>
      <p className="mono muted-text">
        expected {expected.join(", ")} · cited {(result.actual.cited_documents ?? []).join(", ") || "none"}
      </p>
      <ol className="retrieved-list">
        {(result.actual.retrieved ?? []).map((item) => (
          <li
            key={`${item.rank}-${item.citation_id}`}
            className={expected.includes(item.document_name ?? "") ? "expected" : ""}
          >
            <span className="mono">#{item.rank}</span>
            <span className="citation-chip">{item.citation_id}</span>
            <span>
              {item.document_name}
              {item.page ? ` · page ${item.page}` : ""}
            </span>
            <span className="mono muted-text">{item.score !== null ? percent(item.score) : ""}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ResultRow({ result }: { result: EvaluationResult }) {
  const [open, setOpen] = useState(!result.passed);
  const runHref =
    result.actual_run_type === "team"
      ? `/app/team-runs/${result.actual_run_id}`
      : `/app/runs/${result.actual_run_id}`;
  return (
    <li className={`result-card result-${result.status}`}>
      <button className="result-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="mono">{String(result.case_position + 1).padStart(2, "0")}</span>
        <strong>{result.case_name}</strong>
        <span className="mono muted-text">{result.target_kind}</span>
        <span className={`result-badge result-${result.status}`}>{result.status}</span>
        <span className="mono">{percent(result.score)}</span>
        <span className="mono muted-text">{formatMs(result.duration_ms)}</span>
      </button>
      {open && (
        <div className="result-body">
          <p className="muted-text">{result.input_text}</p>
          <div className="result-columns">
            <div>
              <h3>Expected</h3>
              <ul className="expectation-list">
                {expectationLines(result.expected).map((line) => (
                  <li key={line} className="mono">
                    {line}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3>Actual</h3>
              <dl className="details compact">
                <dt>Status</dt>
                <dd className="mono">{result.actual.status ?? "—"}</dd>
                {result.actual.intent && (
                  <>
                    <dt>Intent</dt>
                    <dd className="mono">{result.actual.intent}</dd>
                  </>
                )}
                <dt>Tools</dt>
                <dd className="mono">{(result.actual.tools ?? []).join(", ") || "none"}</dd>
                {result.actual.policy_decision && (
                  <>
                    <dt>Policy</dt>
                    <dd className="mono">
                      {result.actual.policy_decision}
                      {result.actual.action_type ? ` · ${result.actual.action_type}` : ""}
                    </dd>
                  </>
                )}
                {result.actual.text && (
                  <>
                    <dt>Answer</dt>
                    <dd>{result.actual.text}</dd>
                  </>
                )}
              </dl>
            </div>
          </div>
          <h3>Checks</h3>
          <ul className="check-list">
            {result.checks.map((check) => (
              <li key={check.name} className={check.passed ? "pass" : "fail"}>
                <span aria-hidden="true">{check.passed ? "✓" : "✗"}</span>
                <span className="mono">{check.name}</span>
                {!check.passed && (
                  <span className="muted-text">
                    expected {show(check.expected)} · got {show(check.actual)}
                  </span>
                )}
              </li>
            ))}
          </ul>
          {result.status === "error" && (
            <p className="form-error">{result.failure_reasons.join(" ")}</p>
          )}
          <RagEvidence result={result} />
          {result.actual_run_id && (
            <p className="mono">
              <Link href={runHref}>Open run</Link>
              {result.trace_id && (
                <>
                  {" · "}
                  <Link href={`/app/traces/${result.trace_id}`}>Open trace</Link>
                </>
              )}
            </p>
          )}
        </div>
      )}
    </li>
  );
}

export function EvaluationRunDetail({ runId }: { runId: string }) {
  const organization = useWorkspace();
  const load = useCallback(() => getEvaluationRun(organization.id, runId), [organization.id, runId]);
  const { data: run, error, notFound, loading, reload } = useResource(load);
  const active = !!run && (run.status === "queued" || run.status === "running");
  usePolling(active, reload);
  const datasetId = run?.dataset_id;
  const loadSiblings = useCallback(
    () => (datasetId ? listEvaluationRuns(organization.id, datasetId) : Promise.resolve([])),
    [organization.id, datasetId],
  );
  const siblings = useResource(loadSiblings);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const canManage = organization.role !== "member";

  async function act(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await action();
      reload();
    } catch (problem) {
      setFailure(describeError(problem));
    } finally {
      setBusy(false);
    }
  }
  if (loading) return <LoadingState />;
  if (notFound || !run)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Evaluation run not found" : "Could not load this run"}</h1>
        <p className="muted-text">
          {notFound ? `This run does not exist in ${organization.name}.` : error}
        </p>
        <Link href="/app/evaluations">Back to evaluations</Link>
      </section>
    );
  const others = (siblings.data ?? []).filter(
    (other) => other.id !== run.id && other.status === "completed",
  );
  const baseline = others.find((other) => other.is_baseline);
  const previous = baseline ?? others.find((other) => other.created_at < run.created_at);
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">OBSERVE / EVALUATIONS / {organization.name}</p>
          <h1 className="mono-heading">Evaluation {run.id.slice(0, 8)}</h1>
          <p className="page-description">
            <Link href={`/app/evaluations/datasets/${run.dataset_id}`}>{run.dataset_name}</Link> ·{" "}
            {run.target_names.join(" + ") || "no default target"}
          </p>
        </div>
        <Link href="/app/evaluations">Back to evaluations</Link>
      </div>
      <nav className="operations-strip observe-strip" aria-label="Evaluation summary">
        <div>
          <span>PASS RATE</span>
          <strong>{percent(run.pass_rate)}</strong>
          <small>
            {run.passed_count} passed · {run.failed_count} failed · {run.error_count} errors
          </small>
        </div>
        <div>
          <span>SCORE</span>
          <strong>{percent(run.score)}</strong>
          <small>mean share of checks passed</small>
        </div>
        <div>
          <span>RETRIEVAL</span>
          <strong>{percent(run.retrieval_hit_rate)}</strong>
          <small>
            Hit@K · MRR {run.retrieval_mrr !== null ? run.retrieval_mrr.toFixed(2) : "—"}
          </small>
        </div>
        <div>
          <span>DURATION</span>
          <strong className="mono">{formatMs(run.duration_ms)}</strong>
          <small>{run.case_count} cases</small>
        </div>
        <div>
          <span>CONFIG</span>
          <strong className="mono">{run.config_hash?.slice(0, 10) ?? "—"}</strong>
          <small>target configuration hash</small>
        </div>
      </nav>
      <section className="panel">
        <dl className="details">
          <dt>Status</dt>
          <dd>
            <StatusPill status={run.status} />
            {run.is_baseline && <span className="memory-chip"> baseline</span>}
          </dd>
          <dt>Started</dt>
          <dd>{formatDate(run.started_at)}</dd>
          <dt>Completed</dt>
          <dd>{formatDate(run.completed_at)}</dd>
          {run.error_message && (
            <>
              <dt>Error</dt>
              <dd className="form-error">{run.error_message}</dd>
            </>
          )}
        </dl>
        <div className="button-row">
          {canManage && run.status === "completed" && (
            <button disabled={busy} onClick={() => void act(() => setBaseline(organization.id, run.id, !run.is_baseline))}>
              {run.is_baseline ? "Unmark baseline" : "Mark as baseline"}
            </button>
          )}
          {canManage && active && (
            <button disabled={busy} onClick={() => void act(() => cancelEvaluation(organization.id, run.id))}>
              Cancel evaluation
            </button>
          )}
          {previous && run.status === "completed" && (
            <Link className="secondary-button" href={`/app/evaluations/runs/${run.id}/compare/${previous.id}`}>
              Compare with {previous.is_baseline ? "baseline" : "previous run"} {previous.id.slice(0, 8)} →
            </Link>
          )}
        </div>
        {failure && <p className="form-error" role="alert">{failure}</p>}
        {active && (
          <p className="muted-text" role="status">
            Running on the worker: {run.results.length} of {run.case_count} cases evaluated.
          </p>
        )}
      </section>
      <section className="panel">
        <h2>Case results</h2>
        <ol className="result-list">
          {run.results.map((result) => (
            <ResultRow key={result.id} result={result} />
          ))}
        </ol>
        <details className="technical-log">
          <summary>Target snapshot (what was evaluated)</summary>
          <pre className="snapshot">{JSON.stringify(run.target_snapshot, null, 2)}</pre>
        </details>
      </section>
    </>
  );
}
