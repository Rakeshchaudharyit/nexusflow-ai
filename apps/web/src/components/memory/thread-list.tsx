"use client";

import Link from "next/link";
import { useCallback, useState, type FormEvent } from "react";
import { describeError, formatDate, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { LoadingState, PageHeader } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import { createThread, listThreads } from "@/lib/api/memory";

export function ThreadList() {
  const organization = useWorkspace();
  const load = useCallback(() => listThreads(organization.id), [organization.id]);
  const { data: threads, error, loading, reload } = useResource(load);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const title = String(new FormData(form).get("title") ?? "").trim();
    setBusy(true);
    setFailure(null);
    try {
      await createThread(organization.id, title);
      form.reset();
      reload();
    } catch (problem) {
      setFailure(describeError(problem));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        eyebrow={`THREADS / ${organization.name}`}
        title="Threads"
        description="Group agent and team runs so they share thread memory. Runs outside a thread get no thread memory."
      />
      <section className="panel">
        <form onSubmit={create} className="filter-row">
          <label>
            New thread
            <input name="title" required maxLength={200} placeholder="Acme account review" />
          </label>
          <button className="primary-button" disabled={busy}>
            {busy ? "Creating…" : "Create thread"}
          </button>
        </form>
        {failure && <p className="form-error" role="alert">{failure}</p>}
      </section>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <LoadingState />}
      {threads && threads.length === 0 && (
        <p className="muted-text">No threads yet. Create one, then pick it when running an agent or team.</p>
      )}
      {threads && threads.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Runs</th>
                <th>Memory</th>
                <th>Last activity</th>
              </tr>
            </thead>
            <tbody>
              {threads.map((thread) => (
                <tr key={thread.id}>
                  <td>
                    <Link href={`/app/threads/${thread.id}`}>{thread.title}</Link>
                  </td>
                  <td><StatusPill status={thread.status} /></td>
                  <td className="mono">
                    {thread.agent_run_count} agent · {thread.team_run_count} team
                  </td>
                  <td className="mono">{thread.memory_count} active</td>
                  <td className="nowrap">{formatDate(thread.last_activity_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
