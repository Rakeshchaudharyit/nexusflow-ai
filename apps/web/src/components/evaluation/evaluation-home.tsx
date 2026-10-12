"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState, type FormEvent } from "react";
import { describeError, formatDate, usePolling, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { LoadingState, PageHeader } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import { listAgents } from "@/lib/api/agents";
import {
  createDataset,
  createDemoDataset,
  listDatasets,
  listEvaluationRuns,
} from "@/lib/api/evaluation";
import { formatMs, percent } from "@/lib/observability";

export function EvaluationHome() {
  const organization = useWorkspace();
  const router = useRouter();
  const loadDatasets = useCallback(() => listDatasets(organization.id), [organization.id]);
  const loadRuns = useCallback(() => listEvaluationRuns(organization.id), [organization.id]);
  const loadAgents = useCallback(() => listAgents(organization.id), [organization.id]);
  const datasets = useResource(loadDatasets);
  const runs = useResource(loadRuns);
  const agents = useResource(loadAgents);
  usePolling(!!runs.data?.some((run) => run.status === "queued" || run.status === "running"), runs.reload);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canManage = organization.role !== "member";

  async function act(action: () => Promise<{ id: string }>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await action();
      router.push(`/app/evaluations/datasets/${created.id}`);
    } catch (failure) {
      setError(describeError(failure));
      setBusy(false);
    }
  }
  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    void act(() =>
      createDataset(organization.id, {
        name: String(data.get("name") ?? "").trim(),
        description: String(data.get("description") ?? "").trim(),
        dataset_type: String(data.get("dataset_type") ?? "mixed"),
      }),
    );
  }
  function demo(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const agent = String(new FormData(event.currentTarget).get("knowledge_agent_id") ?? "");
    void act(() => createDemoDataset(organization.id, agent || undefined));
  }

  return (
    <>
      <PageHeader
        eyebrow={`OBSERVE / ${organization.name}`}
        title="Evaluations"
        description="Datasets of deterministic expectations, executed through the real agent and team runtime on the background worker. Checks are named for what they verify; there is no LLM judge."
      />
      {canManage && (
        <div className="observe-grid two">
          <form className="panel" onSubmit={create}>
            <h2>New dataset</h2>
            <label>
              Name
              <input name="name" required maxLength={120} placeholder="Release regression" />
            </label>
            <label>
              Description
              <input name="description" maxLength={1000} />
            </label>
            <label>
              Type
              <select name="dataset_type" defaultValue="mixed">
                {["mixed", "agent", "team", "rag", "policy"].map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </select>
            </label>
            <button className="primary-button" disabled={busy}>
              Create dataset
            </button>
          </form>
          <form className="panel" onSubmit={demo}>
            <h2>Demo dataset</h2>
            <p className="field-hint">
              Calculator, customer lookup, MCP, memory recall, team analysis, approval, policy
              deny and adversarial memory; plus RAG citation and no-match when a knowledge agent
              is chosen (it needs knowledge_search and the docs/demo-knowledge source). Memory
              recall runs on a dedicated memory-only agent (no tools, no knowledge), created once
              per workspace.
            </p>
            <label>
              Knowledge agent (RAG cases)
              <select name="knowledge_agent_id" defaultValue="">
                <option value="">None: skip RAG cases</option>
                {(agents.data ?? []).map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </label>
            <button className="primary-button" disabled={busy}>
              Create demo dataset
            </button>
          </form>
        </div>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
      <section className="panel">
        <h2>Datasets</h2>
        {datasets.loading && <LoadingState />}
        {datasets.data && datasets.data.length === 0 && (
          <p className="muted-text">No evaluation datasets yet.</p>
        )}
        {datasets.data && datasets.data.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Dataset</th>
                  <th>Type</th>
                  <th>Cases</th>
                  <th>Runs</th>
                  <th>Last result</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {datasets.data.map((dataset) => (
                  <tr key={dataset.id}>
                    <td>
                      <Link href={`/app/evaluations/datasets/${dataset.id}`}>{dataset.name}</Link>
                    </td>
                    <td className="mono">{dataset.dataset_type}</td>
                    <td className="mono">{dataset.case_count}</td>
                    <td className="mono">{dataset.run_count}</td>
                    <td className="mono">
                      {dataset.last_run
                        ? `${dataset.last_run.passed_count}/${dataset.last_run.case_count} passed`
                        : "—"}
                    </td>
                    <td className="nowrap">{formatDate(dataset.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel">
        <h2>Recent evaluation runs</h2>
        {runs.data && runs.data.length === 0 && <p className="muted-text">No runs yet.</p>}
        {runs.data && runs.data.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Dataset</th>
                  <th>Target</th>
                  <th>Status</th>
                  <th>Cases</th>
                  <th>Passed</th>
                  <th>Failed</th>
                  <th>Pass rate</th>
                  <th>Score</th>
                  <th>Config</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((run) => (
                  <tr key={run.id}>
                    <td className="mono">
                      <Link href={`/app/evaluations/runs/${run.id}`}>{run.id.slice(0, 8)}</Link>
                      {run.is_baseline && <span className="memory-chip"> baseline</span>}
                    </td>
                    <td>{run.dataset_name}</td>
                    <td>{run.target_names.join(" + ") || "—"}</td>
                    <td><StatusPill status={run.status} /></td>
                    <td className="mono">{run.case_count}</td>
                    <td className="mono">{run.passed_count}</td>
                    <td className="mono">{run.failed_count + run.error_count}</td>
                    <td className="mono">{percent(run.pass_rate)}</td>
                    <td className="mono">{percent(run.score)}</td>
                    <td className="mono">{run.config_hash?.slice(0, 10) ?? "—"}</td>
                    <td className="nowrap">
                      {formatDate(run.created_at)} · {formatMs(run.duration_ms)}
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
