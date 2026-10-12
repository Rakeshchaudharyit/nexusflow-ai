"use client";
import { NexusFlowLoader } from "../ui/nexusflow-brand";

import { LoadingState } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback, useState, type FormEvent } from "react";
import {
  describeError,
  formatDate,
  formatDuration,
  usePolling,
  useResource,
} from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { useWorkspace } from "@/components/workspace-shell";
import { displayStatus, executionNote, isRunActive } from "@/lib/jobs";
import {
  getTeam,
  getTeamRun,
  hasAnalysis,
  runTeam,
  updateTeam,
  updateTeamMember,
  type TeamRunResult,
  type TeamStatus,
} from "@/lib/api/teams";
import { ThreadSelect, threadField } from "@/components/memory/thread-select";
import { TeamGraph } from "./team-graph";
import { roleLabel } from "./roles";
import { TeamAction } from "./team-action";
import { TeamOutputView } from "./team-output";

const actions: Record<TeamStatus, { label: string; status: TeamStatus }[]> = {
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
const OBJECTIVE =
  "Analyze Acme Corporation as a potential enterprise opportunity and recommend next steps.";

export function TeamDetail({ teamId }: { teamId: string }) {
  const organization = useWorkspace();
  const load = useCallback(
    () => getTeam(organization.id, teamId),
    [organization.id, teamId],
  );
  const { data: team, error, notFound, loading, reload } = useResource(load);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [objective, setObjective] = useState(OBJECTIVE);
  const [actionError, setActionError] = useState<string | null>(null);
  const [result, setResult] = useState<TeamRunResult | null>(null);
  const canManage = organization.role !== "member";

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await action();
      reload();
    } catch (failure) {
      setActionError(describeError(failure));
    } finally {
      setBusy(false);
    }
  }
  async function execute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget);
    const objective = String(form.get("objective") ?? "");
    const threadId = threadField(form);
    setBusy(true);
    setRunning(true);
    setActionError(null);
    setResult(null);
    try {
      setResult(await runTeam(organization.id, teamId, objective.trim(), threadId));
    } catch (failure) {
      setActionError(describeError(failure));
    } finally {
      setBusy(false);
      setRunning(false);
    }
  }

  if (loading) return <LoadingState />;
  if (notFound || !team)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Team not found" : "Could not load this team"}</h1>
        <p className="muted-text">
          {notFound
            ? `This team does not exist in ${organization.name}.`
            : error}
        </p>
        <Link href="/app/teams">Back to teams</Link>
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
          <p className="eyebrow">TEAMS / {organization.name}</p>
          <h1>{team.name}</h1>
        </div>
        <Link href="/app/teams">Back to teams</Link>
      </div>
      <section className="panel team-summary">
        <dl className="details">
          <dt>Status</dt>
          <dd>
            <StatusPill status={team.status} />
          </dd>
          <dt>Description</dt>
          <dd>{team.description || "—"}</dd>
          <dt>Updated</dt>
          <dd>{formatDate(team.updated_at)}</dd>
          {team.problems.length > 0 && (
            <>
              <dt>Not runnable</dt>
              <dd>{team.problems.join("; ")}</dd>
            </>
          )}
        </dl>
        {canManage && (
          <div className="button-row">
            <button
              disabled={busy}
              onClick={() =>
                void act(() =>
                  updateTeam(organization.id, teamId, {
                    workspace_memory_enabled: !team.workspace_memory_enabled,
                  }),
                )
              }
            >
              Workspace memory: {team.workspace_memory_enabled ? "on" : "off"}
            </button>
            {actions[team.status].map((action) => (
              <button
                key={action.status}
                disabled={busy}
                onClick={() =>
                  void act(() =>
                    updateTeam(organization.id, teamId, {
                      status: action.status,
                    }),
                  )
                }
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
      </section>
      <TeamGraph members={team.members} />
      <section className="panel">
        <h2>Members & permissions</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Agent</th>
                <th>Agent status</th>
                <th>Allowed tools</th>
                <th>Required</th>
              </tr>
            </thead>
            <tbody>
              {team.members.map((member) => (
                <tr key={member.id}>
                  <td>{roleLabel(member.role)}</td>
                  <td>
                    <Link href={`/app/agents/${member.agent_id}`}>
                      {member.agent_name}
                    </Link>
                  </td>
                  <td>
                    <StatusPill status={member.agent_status} />
                  </td>
                  <td className="mono">
                    {member.tools.length
                      ? member.tools
                          .map(
                            (tool) =>
                              `${tool.tool_key}${tool.is_enabled ? "" : " (off)"}`,
                          )
                          .join(", ")
                      : "none"}
                    {!!member.knowledge_sources?.length && (
                      <span className="muted-text">
                        {" · knowledge: "}
                        {member.knowledge_sources.map((source, index) => (
                          <span key={source.source_id}>
                            {index > 0 && ", "}
                            <Link href={`/app/knowledge/${source.source_id}`}>
                              {source.source_name}
                            </Link>
                            {source.is_enabled ? "" : " (off)"}
                          </span>
                        ))}
                      </span>
                    )}
                  </td>
                  <td>
                    {canManage && team.status !== "archived" ? (
                      <label className="inline-toggle">
                        <input
                          type="checkbox"
                          checked={member.is_required}
                          disabled={busy}
                          onChange={(event) =>
                            void act(() =>
                              updateTeamMember(
                                organization.id,
                                teamId,
                                member.id,
                                {
                                  is_required: event.target.checked,
                                },
                              ),
                            )
                          }
                        />
                        <span className="sr-only">
                          Required: {member.agent_name}
                        </span>
                      </label>
                    ) : member.is_required ? (
                      "Yes"
                    ) : (
                      "No"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="field-hint">
          Tool access is configured per agent on the agent&apos;s page. Members
          only reach their own enabled assignments. A member with{" "}
          <span className="mono">internal:knowledge_search</span> searches only its own
          agent&apos;s knowledge sources; in this team the researcher consults them and the
          writer cites what it found.
        </p>
      </section>
      <section className="panel" id="run">
        <h2>Run team</h2>
        <div className="composer-examples" aria-label="Example objectives">{["Analyze Acme Corporation as a potential enterprise opportunity.", "Prepare a follow-up email for Acme Corporation.", "Create an internal CRM note for Acme Corporation."].map((example,index) => <button type="button" key={example} disabled={busy} onClick={() => setObjective(example)}>{["Account analysis", "Follow-up email", "CRM note"][index]}</button>)}</div>
        <form onSubmit={execute}>
          <label>
            Objective
            <textarea
              name="objective"
              required
              maxLength={2000}
              rows={3}
              value={objective}
              onChange={event => setObjective(event.target.value)}
            />
          </label>
          <ThreadSelect />
          <button
            className="primary-button"
            disabled={busy || team.status !== "active"}
          >
            {busy ? "Running…" : "Run Team"}
          </button>
          {team.status !== "active" && (
            <p className="field-hint">Only active teams can run.</p>
          )}
        </form>
        {actionError && (
          <p className="form-error" role="alert">
            {actionError}
          </p>
        )}
        {running && <NexusFlowLoader label="Submitting team run…"/>}
      {result && <LiveTeamRun key={result.run_id} initial={result} />}
      </section>
    </>
  );
}

/** The run just submitted, followed through queued → running → outcome (M7: the team runs
 * in the background worker; this view polls every 2 s until the run settles or pauses). */
function LiveTeamRun({ initial }: { initial: TeamRunResult }) {
  const organization = useWorkspace();
  const load = useCallback(
    () => getTeamRun(organization.id, initial.run_id),
    [organization.id, initial.run_id],
  );
  const { data: run, reload } = useResource(load);
  const status = run?.status ?? initial.status;
  usePolling(isRunActive(status), reload);
  const view = run
    ? {
        status: displayStatus(run.status, run.execution_status),
        agents: run.results
          .filter((step) => step.status === "completed")
          .map((step) => step.role),
        duration: run.duration_ms,
        steps: run.step_count,
        error: run.error,
        action: run.action,
        output: run.final_output,
        execution: run.execution,
      }
    : {
        status: initial.status,
        agents: initial.agents_executed,
        duration: initial.duration_ms,
        steps: initial.step_count,
        error: initial.error,
        action: initial.action,
        output: initial.final_output,
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
        <dt>Agents executed</dt>
        <dd>
          {view.agents.map(roleLabel).join(" → ") ||
            (isRunActive(status) ? "none yet" : "none")}
        </dd>
        <dt>Duration</dt>
        <dd>
          {formatDuration(view.duration)} · {view.steps} steps
        </dd>
        {view.error && (
          <>
            <dt>Error</dt>
            <dd>
              {view.error.message} ({view.error.code})
            </dd>
          </>
        )}
      </dl>
      {note && <p className="muted-text">{note}</p>}
      {isRunActive(status) && (
        <NexusFlowLoader
          label={
            status === "queued" ? "Queued for a worker…" : "Running on a worker…"
          }
        />
      )}
      {view.action && <TeamAction action={view.action} />}
      {hasAnalysis(view.output) && <TeamOutputView output={view.output} />}
      <Link href={`/app/team-runs/${initial.run_id}`}>View Run Details</Link>
    </div>
  );
}
