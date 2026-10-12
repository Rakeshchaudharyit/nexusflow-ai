"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState, type FormEvent } from "react";
import { describeError, formatDate, usePolling, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { LoadingState } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import { listAgents } from "@/lib/api/agents";
import {
  addCase,
  deleteCase,
  deleteDataset,
  getDataset,
  startEvaluation,
  type CaseInput,
} from "@/lib/api/evaluation";
import { listTeams } from "@/lib/api/teams";
import { expectationLines, parseValues, phrases } from "@/lib/evaluation";
import { formatMs, percent } from "@/lib/observability";

function CaseForm({ onAdd, busy }: { onAdd: (input: CaseInput) => void; busy: boolean }) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const text = (key: string) => String(data.get(key) ?? "").trim();
    const input: CaseInput = {
      name: text("name"),
      target_kind: text("target_kind") as "agent" | "team",
      input_text: text("input_text"),
      expected_status: text("expected_status") || null,
      expected_intent: text("expected_intent") || null,
      expected_tool_key: text("expected_tool_key") || null,
      expected_output_contains: phrases(text("expected_output_contains")),
      expected_citation_documents: phrases(text("expected_citation_documents")),
      expected_policy_decision: text("expected_policy_decision") || null,
      expected_values: parseValues(text("expected_values")),
      expected_no_match: data.get("expected_no_match") === "on",
    };
    onAdd(input);
    event.currentTarget.reset();
  }
  return (
    <form className="panel" onSubmit={submit}>
      <h2>Add case</h2>
      <div className="form-grid">
        <label>
          Name
          <input name="name" required maxLength={120} placeholder="Calculator" />
        </label>
        <label>
          Target
          <select name="target_kind" defaultValue="agent">
            <option value="agent">Agent</option>
            <option value="team">Team</option>
          </select>
        </label>
        <label className="span-2">
          Input
          <textarea name="input_text" required rows={2} maxLength={4000} placeholder="125 multiplied by 24." />
        </label>
        <label>
          Expected status
          <select name="expected_status" defaultValue="">
            <option value="">Any</option>
            {["completed", "failed", "awaiting_approval", "cancelled"].map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label>
          Expected intent
          <input name="expected_intent" maxLength={40} placeholder="calculation" />
        </label>
        <label>
          Expected tool
          <input name="expected_tool_key" maxLength={300} placeholder="internal:calculator · mcp:*:calculate · none" />
        </label>
        <label>
          Policy decision
          <select name="expected_policy_decision" defaultValue="">
            <option value="">Not checked</option>
            {["none", "allow", "require_approval", "deny"].map((decision) => (
              <option key={decision} value={decision}>
                {decision}
              </option>
            ))}
          </select>
        </label>
        <label>
          Output contains (comma-separated)
          <input name="expected_output_contains" placeholder="3000" />
        </label>
        <label>
          Cited documents (RAG)
          <input name="expected_citation_documents" placeholder="Enterprise Security Requirements.pdf" />
        </label>
        <label className="span-2">
          Expected values (one path=value per line)
          <textarea name="expected_values" rows={2} placeholder={"opportunity_score=92\nvalidation.confidence=0.95"} />
        </label>
        <label className="inline-toggle">
          <input type="checkbox" name="expected_no_match" /> Expect the no-match response
        </label>
      </div>
      <button className="primary-button" disabled={busy}>
        Add case
      </button>
    </form>
  );
}

export function DatasetDetail({ datasetId }: { datasetId: string }) {
  const organization = useWorkspace();
  const router = useRouter();
  const load = useCallback(() => getDataset(organization.id, datasetId), [organization.id, datasetId]);
  const loadAgents = useCallback(() => listAgents(organization.id, "active"), [organization.id]);
  const loadTeams = useCallback(() => listTeams(organization.id), [organization.id]);
  const { data: dataset, error, notFound, loading, reload } = useResource(load);
  const agents = useResource(loadAgents);
  const teams = useResource(loadTeams);
  usePolling(
    !!dataset?.runs.some((run) => run.status === "queued" || run.status === "running"),
    reload,
  );
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const canManage = organization.role !== "member";

  async function act(action: () => Promise<unknown>, after?: (value: unknown) => void) {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      const value = await action();
      if (after) after(value);
      else reload();
    } catch (problem) {
      setFailure(describeError(problem));
    } finally {
      setBusy(false);
    }
  }
  function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const agent = String(data.get("target_agent_id") ?? "");
    const team = String(data.get("target_team_id") ?? "");
    void act(
      () =>
        startEvaluation(organization.id, datasetId, {
          ...(agent ? { target_agent_id: agent } : {}),
          ...(team ? { target_team_id: team } : {}),
        }),
      (run) => router.push(`/app/evaluations/runs/${(run as { id: string }).id}`),
    );
  }

  if (loading) return <LoadingState />;
  if (notFound || !dataset)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Dataset not found" : "Could not load this dataset"}</h1>
        <p className="muted-text">
          {notFound ? `This dataset does not exist in ${organization.name}.` : error}
        </p>
        <Link href="/app/evaluations">Back to evaluations</Link>
      </section>
    );
  const needsAgent = dataset.cases.some((c) => c.target_kind === "agent" && !c.target_agent_id);
  const needsTeam = dataset.cases.some((c) => c.target_kind === "team" && !c.target_team_id);
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">OBSERVE / EVALUATIONS / {organization.name}</p>
          <h1>{dataset.name}</h1>
          {dataset.description && <p className="page-description">{dataset.description}</p>}
        </div>
        <Link href="/app/evaluations">Back to evaluations</Link>
      </div>
      {canManage && (
        <form className="panel" onSubmit={start}>
          <h2>Run evaluation</h2>
          <p className="field-hint">
            Cases run on the background worker through the real runtime. Agent cases use the
            agent below unless the case names its own; team cases use the team. Approval cases
            are never approved: their runs are cancelled after checking.
          </p>
          <div className="filter-row">
            <label>
              Agent {needsAgent ? "(required)" : "(optional)"}
              <select name="target_agent_id" defaultValue="" required={needsAgent}>
                <option value="">None</option>
                {(agents.data ?? []).map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Team {needsTeam ? "(required)" : "(optional)"}
              <select name="target_team_id" defaultValue="" required={needsTeam}>
                <option value="">None</option>
                {(teams.data ?? [])
                  .filter((team) => team.status === "active")
                  .map((team) => (
                    <option key={team.id} value={team.id}>
                      {team.name}
                    </option>
                  ))}
              </select>
            </label>
            <button className="primary-button" disabled={busy || !dataset.cases.length}>
              {busy ? "Queuing…" : "Run evaluation"}
            </button>
          </div>
        </form>
      )}
      {failure && <p className="form-error" role="alert">{failure}</p>}
      <section className="panel">
        <h2>Cases · {dataset.cases.length}</h2>
        {dataset.cases.length === 0 ? (
          <p className="muted-text">No cases yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Case</th>
                  <th>Target</th>
                  <th>Input</th>
                  <th>Expectations</th>
                  {canManage && <th />}
                </tr>
              </thead>
              <tbody>
                {dataset.cases.map((item, index) => (
                  <tr key={item.id}>
                    <td className="mono">{String(index + 1).padStart(2, "0")}</td>
                    <td>{item.name}</td>
                    <td className="mono">
                      {item.target_kind}
                      {item.target_agent_id || item.target_team_id ? " · fixed" : ""}
                    </td>
                    <td className="muted-text">
                      {item.setup_inputs.length > 0 && (
                        <span className="memory-chip">setup {item.setup_inputs.length}</span>
                      )}
                      {item.setup_memory.length > 0 && (
                        <span className="memory-chip">memory {item.setup_memory.length}</span>
                      )}{" "}
                      {item.input_text}
                    </td>
                    <td>
                      <ul className="expectation-list">
                        {expectationLines(item).map((line) => (
                          <li key={line} className="mono">
                            {line}
                          </li>
                        ))}
                      </ul>
                    </td>
                    {canManage && (
                      <td>
                        <button
                          disabled={busy}
                          onClick={() => void act(() => deleteCase(organization.id, item.id))}
                        >
                          Remove
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {canManage && (
        <CaseForm busy={busy} onAdd={(input) => void act(() => addCase(organization.id, datasetId, input))} />
      )}
      <section className="panel">
        <h2>Runs</h2>
        {dataset.runs.length === 0 ? (
          <p className="muted-text">Not run yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Target</th>
                  <th>Passed</th>
                  <th>Pass rate</th>
                  <th>Score</th>
                  <th>Config</th>
                  <th>Duration</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {dataset.runs.map((run) => (
                  <tr key={run.id}>
                    <td className="mono">
                      <Link href={`/app/evaluations/runs/${run.id}`}>{run.id.slice(0, 8)}</Link>
                      {run.is_baseline && <span className="memory-chip"> baseline</span>}
                    </td>
                    <td><StatusPill status={run.status} /></td>
                    <td>{run.target_names.join(" + ")}</td>
                    <td className="mono">
                      {run.passed_count}/{run.case_count}
                    </td>
                    <td className="mono">{percent(run.pass_rate)}</td>
                    <td className="mono">{percent(run.score)}</td>
                    <td className="mono">{run.config_hash?.slice(0, 10) ?? "—"}</td>
                    <td className="mono">{formatMs(run.duration_ms)}</td>
                    <td className="nowrap">{formatDate(run.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {canManage && (
        <button
          className="danger-button"
          disabled={busy}
          onClick={() => {
            if (window.confirm(`Delete ${dataset.name}, its runs and their results?`))
              void act(
                () => deleteDataset(organization.id, datasetId),
                () => router.push("/app/evaluations"),
              );
          }}
        >
          Delete dataset
        </button>
      )}
    </>
  );
}
