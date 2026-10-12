"use client";

import Link from "next/link";
import { useCallback } from "react";
import { useResource } from "@/components/agents/resource";
import { LoadingState } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import { compareRuns, type EvaluationRunSummary } from "@/lib/api/evaluation";
import { CHANGE_LABELS } from "@/lib/evaluation";
import { formatMs, percent, signedMs, signedPercent } from "@/lib/observability";

function Side({ label, run }: { label: string; run: EvaluationRunSummary }) {
  return (
    <section className="panel compare-side">
      <p className="eyebrow">{label}</p>
      <h2 className="mono">
        <Link href={`/app/evaluations/runs/${run.id}`}>{run.id.slice(0, 8)}</Link>
        {run.is_baseline && <span className="memory-chip"> baseline</span>}
      </h2>
      <dl className="details compact">
        <dt>Pass rate</dt>
        <dd className="mono">
          {percent(run.pass_rate)} ({run.passed_count}/{run.case_count})
        </dd>
        <dt>Score</dt>
        <dd className="mono">{percent(run.score)}</dd>
        <dt>Duration</dt>
        <dd className="mono">{formatMs(run.duration_ms)}</dd>
        <dt>Config</dt>
        <dd className="mono">{run.config_hash?.slice(0, 16) ?? "—"}</dd>
        <dt>Target</dt>
        <dd>{run.target_names.join(" + ")}</dd>
      </dl>
    </section>
  );
}

export function EvaluationCompare({ runId, otherId }: { runId: string; otherId: string }) {
  const organization = useWorkspace();
  const load = useCallback(
    () => compareRuns(organization.id, runId, otherId),
    [organization.id, runId, otherId],
  );
  const { data, error, loading } = useResource(load);
  if (loading) return <LoadingState />;
  if (!data)
    return (
      <section className="panel narrow">
        <h1>Could not compare these runs</h1>
        <p className="muted-text">{error}</p>
        <Link href={`/app/evaluations/runs/${runId}`}>Back to the run</Link>
      </section>
    );
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">OBSERVE / EVALUATIONS / COMPARE</p>
          <h1>Run comparison</h1>
          <p className="page-description">
            {data.current.dataset_name} · a regression is a case that passed before and fails now;
            an improvement is the reverse. No statistical significance is implied.
          </p>
        </div>
        <Link href={`/app/evaluations/runs/${runId}`}>Back to the run</Link>
      </div>
      <div className="observe-grid two">
        <Side label="PREVIOUS" run={data.previous} />
        <Side label="CURRENT" run={data.current} />
      </div>
      <nav className="operations-strip observe-strip" aria-label="Changes">
        <div className={data.regressions ? "strip-alert" : ""}>
          <span>REGRESSIONS</span>
          <strong>{String(data.regressions).padStart(2, "0")}</strong>
          <small>passed before, failing now</small>
        </div>
        <div>
          <span>IMPROVEMENTS</span>
          <strong>{String(data.improvements).padStart(2, "0")}</strong>
          <small>failing before, passing now</small>
        </div>
        <div>
          <span>PASS RATE</span>
          <strong className="mono">{signedPercent(data.pass_rate_change)}</strong>
          <small>score {signedPercent(data.score_change)}</small>
        </div>
        <div>
          <span>DURATION</span>
          <strong className="mono">{signedMs(data.duration_change_ms)}</strong>
          <small>{data.config_changed ? "configuration changed" : "same configuration"}</small>
        </div>
      </nav>
      <section className="panel">
        <h2>Cases</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Case</th>
                <th>Change</th>
                <th>Previous</th>
                <th>Current</th>
                <th>Failing checks now</th>
              </tr>
            </thead>
            <tbody>
              {data.cases.map((item) => (
                <tr key={item.case_id} className={`change-row change-${item.change}`}>
                  <td>{item.case_name}</td>
                  <td>
                    <span className={`result-badge change-${item.change}`}>
                      {CHANGE_LABELS[item.change]}
                    </span>
                  </td>
                  <td className="mono">
                    {item.previous_status ?? "—"} · {percent(item.previous_score)}
                  </td>
                  <td className="mono">
                    {item.current_status ?? "—"} · {percent(item.current_score)}
                  </td>
                  <td className="mono">{item.failed_checks.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
