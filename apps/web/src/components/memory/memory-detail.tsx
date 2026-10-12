"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState, type FormEvent } from "react";
import { useAuth } from "@/components/auth-provider";
import { describeError, formatDate, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { LoadingState } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import { deleteMemory, getMemory, updateMemory } from "@/lib/api/memory";
import { memoryStatus, removalLabel, scopeLabel, sourceLabel } from "@/lib/memory";

export function MemoryDetail({ memoryId }: { memoryId: string }) {
  const organization = useWorkspace();
  const { user } = useAuth();
  const router = useRouter();
  const load = useCallback(
    () => getMemory(organization.id, memoryId),
    [organization.id, memoryId],
  );
  const { data: entry, error, notFound, loading, reload } = useResource(load);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function act(action: () => Promise<unknown>, after?: () => void) {
    if (busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await action();
      (after ?? reload)();
    } catch (problem) {
      setFailure(describeError(problem));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState />;
  if (notFound || !entry)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Memory not found" : "Could not load this memory"}</h1>
        <p className="muted-text">
          {notFound ? `This memory does not exist in ${organization.name}.` : error}
        </p>
        <Link href="/app/memory">Back to memory</Link>
      </section>
    );
  const manual = entry.source_type === "manual_user_entry";
  // The API enforces the same rule; this only hides controls that would be refused.
  const canModify =
    organization.role !== "member" || (manual && entry.created_by_user_id === user?.id);

  function edit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("value") ?? "").trim();
    void act(() =>
      updateMemory(organization.id, memoryId, entry!.fact_key ? { fact_value: value } : { content: value }),
    );
  }

  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">MEMORY / {organization.name}</p>
          <h1>{entry.fact_key ?? entry.memory_type.replace("_", " ")}</h1>
        </div>
        <Link href="/app/memory">Back to memory</Link>
      </div>
      <section className="panel">
        <dl className="details">
          <dt>Status</dt>
          <dd>
            <StatusPill status={memoryStatus(entry)} />{" "}
            {!entry.in_context && entry.is_active && "Expired: no longer injected into runs."}
          </dd>
          <dt>Content</dt>
          <dd className="preformatted">{entry.fact_key ? `${entry.fact_key} = ${entry.fact_value}` : entry.content}</dd>
          <dt>Type / scope</dt>
          <dd>
            <span className="memory-chip">{entry.memory_type}</span>{" "}
            {scopeLabel(entry.scope)}
          </dd>
          {entry.thread_id && (
            <>
              <dt>Thread</dt>
              <dd><Link href={`/app/threads/${entry.thread_id}`}>{entry.thread_title ?? entry.thread_id}</Link></dd>
            </>
          )}
          {entry.agent_id && (
            <>
              <dt>Agent</dt>
              <dd><Link href={`/app/agents/${entry.agent_id}`}>{entry.agent_name ?? entry.agent_id}</Link></dd>
            </>
          )}
          {entry.team_id && (
            <>
              <dt>Team</dt>
              <dd><Link href={`/app/teams/${entry.team_id}`}>View team</Link></dd>
            </>
          )}
          <dt>Source</dt>
          <dd>
            {sourceLabel(entry.source_type)}
            {entry.source_id && entry.source_type === "agent_run" && <> · <Link href={`/app/runs/${entry.source_id}`}>run</Link></>}
            {entry.source_id && entry.source_type === "team_run" && <> · <Link href={`/app/team-runs/${entry.source_id}`}>team run</Link></>}
            {entry.source_id && entry.source_type === "approved_action" && <> · <Link href={`/app/approvals/${entry.source_id}`}>approval</Link></>}
          </dd>
          {entry.confidence !== null && (
            <>
              <dt>Confidence</dt>
              <dd className="mono">{Math.round(entry.confidence * 100)}%</dd>
            </>
          )}
          <dt>Importance</dt>
          <dd className="mono">{entry.importance} / 5{entry.pinned ? " · pinned" : ""}</dd>
          <dt>Created</dt>
          <dd>{formatDate(entry.created_at)}</dd>
          <dt>Updated</dt>
          <dd>{formatDate(entry.updated_at)}</dd>
          <dt>Expires</dt>
          <dd>{formatDate(entry.expires_at)}</dd>
        </dl>
        {failure && <p className="form-error" role="alert">{failure}</p>}
        {canModify && (
          <div className="button-row">
            <button disabled={busy} onClick={() => void act(() => updateMemory(organization.id, memoryId, { pinned: !entry.pinned }))}>
              {entry.pinned ? "Unpin" : "Pin"}
            </button>
            {!entry.is_active && (
              <button disabled={busy} onClick={() => void act(() => updateMemory(organization.id, memoryId, { is_active: true }))}>
                Reactivate
              </button>
            )}
            {(manual || entry.is_active) && (
              <button
                disabled={busy}
                onClick={() =>
                  void act(
                    () => deleteMemory(organization.id, memoryId),
                    manual ? () => router.push("/app/memory") : reload,
                  )
                }
              >
                {removalLabel(entry)}
              </button>
            )}
          </div>
        )}
      </section>
      {canModify && manual && (
        <section className="panel">
          <h2>Edit manual memory</h2>
          <form onSubmit={edit}>
            <label>
              {entry.fact_key ? "Value" : "Content"}
              <textarea
                name="value"
                required
                maxLength={entry.fact_key ? 500 : 2000}
                rows={2}
                defaultValue={entry.fact_key ? (entry.fact_value ?? "") : entry.content}
              />
            </label>
            <button className="primary-button" disabled={busy}>Save</button>
          </form>
        </section>
      )}
      {!manual && (
        <p className="field-hint">Memory derived from runs keeps its recorded content for traceability; it can be deactivated but not rewritten.</p>
      )}
    </>
  );
}
