"use client";
import { NexusFlowLoader, identityCode } from "../ui/nexusflow-brand";

import { LoadingState } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback, useState, type FormEvent } from "react";
import { useWorkspace } from "@/components/workspace-shell";
import { displayStatus, executionNote, isRunActive } from "@/lib/jobs";
import {
  getAgent,
  getRun,
  runAgent,
  updateAgent,
  type AgentStatus,
  type RunResult,
} from "@/lib/api/agents";
import {
  describeError,
  formatDate,
  formatDuration,
  usePolling,
  useResource,
} from "./resource";
import { ThreadSelect, threadField } from "@/components/memory/thread-select";
import { AgentKnowledge } from "@/components/knowledge/agent-knowledge";
import { CitationList, CitedText } from "@/components/knowledge/citations";
import { AgentTools } from "./agent-tools";
import { StatusPill } from "./status-pill";
import { ToolCalls } from "./tool-calls";

const actions: Record<AgentStatus, { label: string; status: AgentStatus }[]> = {
  draft: [
    { label: "Activate", status: "active" },
    { label: "Archive", status: "archived" },
  ],
  active: [
    { label: "Move to draft", status: "draft" },
    { label: "Archive", status: "archived" },
  ],
  archived: [{ label: "Restore to draft", status: "draft" }],
};

export function AgentDetail({ agentId }: { agentId: string }) {
  const organization = useWorkspace();
  const load = useCallback(
    () => getAgent(organization.id, agentId),
    [organization.id, agentId],
  );
  const { data: agent, error, notFound, loading, reload } = useResource(load);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [result, setResult] = useState<RunResult | null>(null);
  const [toolsVersion, setToolsVersion] = useState(0);
  const [editing, setEditing] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const canManage = organization.role !== "member";

  async function changeStatus(status: AgentStatus) {
    setBusy(true);
    setEditError(null);
    try {
      await updateAgent(organization.id, agentId, { status });
      reload();
    } catch (failure) {
      setEditError(describeError(failure));
    } finally {
      setBusy(false);
    }
  }
  async function saveDetails(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    setBusy(true);
    setEditError(null);
    try {
      await updateAgent(organization.id, agentId, {
        name: value("name"),
        description: value("description"),
        instructions: value("instructions"),
      });
      setEditing(false);
      reload();
    } catch (failure) {
      setEditError(describeError(failure));
    } finally {
      setBusy(false);
    }
  }
  async function execute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget);
    const input = String(form.get("input") ?? "");
    const threadId = threadField(form);
    setBusy(true);
    setRunning(true);
    setActionError(null);
    setResult(null);
    try {
      setResult(await runAgent(organization.id, agentId, input.trim(), threadId));
    } catch (failure) {
      setActionError(describeError(failure));
    } finally {
      setBusy(false);
      setRunning(false);
    }
  }

  if (loading) return <LoadingState />;
  if (notFound || !agent)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Agent not found" : "Could not load this agent"}</h1>
        <p className="muted-text">
          {notFound
            ? `This agent does not exist in ${organization.name}.`
            : error}
        </p>
        <Link href="/app/agents">Back to agents</Link>
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
          <p className="eyebrow">AGENTS / {organization.name}</p>
          <div className="agent-title"><span className="agent-code">{identityCode(agent.name)}</span><h1>{agent.name}</h1></div>
        </div>
        <Link href="/app/agents">Back to agents</Link>
      </div>
      <div className="agent-detail-grid"><div>
      <section className="panel">
        <h2>Agent configuration</h2>
        {editing ? (
          <form onSubmit={saveDetails}>
            <label>
              Name
              <input
                name="name"
                required
                maxLength={120}
                pattern=".*\S.*"
                defaultValue={agent.name}
              />
            </label>
            <label>
              Description
              <input
                name="description"
                maxLength={500}
                defaultValue={agent.description ?? ""}
              />
            </label>
            <label>
              Instructions
              <textarea
                name="instructions"
                required
                maxLength={4000}
                rows={5}
                defaultValue={agent.instructions}
              />
            </label>
            {editError && (
              <p className="form-error" role="alert">
                {editError}
              </p>
            )}
            <div className="button-row">
              <button className="primary-button" disabled={busy}>
                {busy ? "Saving…" : "Save changes"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => setEditing(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <dl className="details">
            <dt>Status</dt>
            <dd>
              <StatusPill status={agent.status} />
            </dd>
            <dt>Description</dt>
            <dd>{agent.description || "—"}</dd>
            <dt>Instructions</dt>
            <dd className="preformatted">{agent.instructions}</dd>
            <dt>Slug</dt>
            <dd className="mono">{agent.slug}</dd>
            <dt>Updated</dt>
            <dd>{formatDate(agent.updated_at)}</dd>
          </dl>
        )}
        {canManage && !editing && (
          <div className="button-row">
            <button
              disabled={busy}
              onClick={() => {
                setEditError(null);
                setEditing(true);
              }}
            >
              Edit details
            </button>
            <button
              disabled={busy}
              onClick={() =>
                void updateAgent(organization.id, agentId, {
                  workspace_memory_enabled: !agent.workspace_memory_enabled,
                }).then(reload, (failure: unknown) => setEditError(describeError(failure)))
              }
            >
              Workspace memory: {agent.workspace_memory_enabled ? "on" : "off"}
            </button>
            {actions[agent.status].map((action) => (
              <button
                key={action.status}
                disabled={busy}
                onClick={() => void changeStatus(action.status)}
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
        {editError && !editing && (
          <p className="form-error" role="alert">
            {editError}
          </p>
        )}
      </section>
      <AgentTools agentId={agentId} onChanged={() => setToolsVersion((value) => value + 1)} />
      <AgentKnowledge agentId={agentId} toolsVersion={toolsVersion} />
      </div>
      <section className="panel">
        <h2>Test console</h2>
        <form onSubmit={execute}>
          <label>
            Input
            <textarea
              name="input"
              required
              maxLength={2000}
              rows={3}
              placeholder="Look up Acme Corporation and summarize the account."
            />
          </label>
          <ThreadSelect />
          <button
            className="primary-button"
            disabled={busy || agent.status !== "active"}
          >
            {busy ? "Running…" : "Run Agent"}
          </button>
          {agent.status !== "active" && (
            <p className="field-hint">Only active agents can run.</p>
          )}
        </form>
        {actionError && (
          <p className="form-error" role="alert">
            {actionError}
          </p>
        )}
        {running && <NexusFlowLoader label="Submitting run…"/>}
      {result && <LiveAgentRun key={result.run_id} initial={result} />}
      </section>
      </div>
    </>
  );
}

/** The run just submitted, followed through queued → running → outcome (M7: the graph runs
 * in the background worker; this view polls every 2 s until the run settles). */
function LiveAgentRun({ initial }: { initial: RunResult }) {
  const organization = useWorkspace();
  const load = useCallback(
    () => getRun(organization.id, initial.run_id),
    [organization.id, initial.run_id],
  );
  const { data: run, reload } = useResource(load);
  const status = run?.status ?? initial.status;
  usePolling(isRunActive(status), reload);
  const view = run
    ? {
        status: displayStatus(run.status, run.execution_status),
        intent: run.final_output?.intent ?? (run.state?.intent as string | undefined),
        summary: run.final_output?.summary ?? null,
        citations: run.final_output?.citations ?? [],
        error: run.error,
        duration: run.duration_ms,
        steps: run.step_count,
        calls: run.tool_calls,
        execution: run.execution,
      }
    : {
        status: initial.status,
        intent: initial.intent,
        summary: initial.summary,
        citations: [],
        error: initial.error,
        duration: initial.duration_ms,
        steps: initial.step_count,
        calls: initial.tool_calls,
        execution: initial.execution,
      };
  const note = executionNote(view.execution);
  return (
    <div className="run-result" aria-live="polite">
      <dl className="details">
        <dt>Status</dt>
        <dd>
          <StatusPill status={view.status} />
        </dd>
        <dt>Intent</dt>
        <dd className="mono">{view.intent ?? "—"}</dd>
        <dt>{view.error ? "Error" : "Output"}</dt>
        <dd className="cited-text">
          {view.error ? (
            view.error.message
          ) : view.summary ? (
            <CitedText text={view.summary} citations={view.citations} />
          ) : (
            "—"
          )}
        </dd>
        <dt>Duration</dt>
        <dd>{formatDuration(view.duration)}</dd>
        <dt>Steps</dt>
        <dd>{view.steps}</dd>
      </dl>
      {note && <p className="muted-text">{note}</p>}
      {isRunActive(status) && (
        <NexusFlowLoader
          label={
            status === "queued" ? "Queued for a worker…" : "Running on a worker…"
          }
        />
      )}
      <ToolCalls calls={view.calls} />
      <CitationList citations={view.citations} />
      <Link href={`/app/runs/${initial.run_id}`}>View Run Details</Link>
    </div>
  );
}
