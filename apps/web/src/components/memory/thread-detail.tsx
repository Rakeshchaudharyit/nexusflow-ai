"use client";

import Link from "next/link";
import { useCallback } from "react";
import { formatDate, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { LoadingState } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import { getThread, updateThread } from "@/lib/api/memory";
import { sourceLabel } from "@/lib/memory";
import { MemoryForm } from "./memory-form";
import { MemoryTable } from "./memory-table";

export function ThreadDetail({ threadId }: { threadId: string }) {
  const organization = useWorkspace();
  const load = useCallback(
    () => getThread(organization.id, threadId),
    [organization.id, threadId],
  );
  const { data: thread, error, notFound, loading, reload } = useResource(load);
  if (loading) return <LoadingState />;
  if (notFound || !thread)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Thread not found" : "Could not load this thread"}</h1>
        <p className="muted-text">
          {notFound ? `This thread does not exist in ${organization.name}.` : error}
        </p>
        <Link href="/app/threads">Back to threads</Link>
      </section>
    );
  const archived = thread.status === "archived";
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">THREADS / {organization.name}</p>
          <h1>{thread.title}</h1>
        </div>
        <Link href="/app/threads">Back to threads</Link>
      </div>
      <section className="panel">
        <dl className="details">
          <dt>Status</dt>
          <dd><StatusPill status={thread.status} /></dd>
          <dt>Last activity</dt>
          <dd>{formatDate(thread.last_activity_at)}</dd>
          <dt>Runs</dt>
          <dd className="mono">{thread.agent_run_count} agent · {thread.team_run_count} team</dd>
          <dt>Active memory</dt>
          <dd className="mono">{thread.memory_count}</dd>
        </dl>
        <div className="button-row">
          <button
            onClick={() =>
              void updateThread(organization.id, threadId, {
                status: archived ? "active" : "archived",
              }).then(reload, reload)
            }
          >
            {archived ? "Reopen thread" : "Archive thread"}
          </button>
        </div>
      </section>
      <section className="panel">
        <h2>Thread summary</h2>
        <p className={thread.summary ? "" : "muted-text"}>
          {thread.summary ?? "No summary yet. One is generated deterministically once the thread holds enough memory."}
        </p>
      </section>
      <section className="panel">
        <h2>Key facts</h2>
        {thread.facts.length === 0 ? (
          <p className="muted-text">No facts yet. A completed customer lookup or validated team run in this thread records them.</p>
        ) : (
          <dl className="details">
            {thread.facts.map((fact) => (
              <div key={fact.id} style={{ display: "contents" }}>
                <dt className="mono">{fact.key}</dt>
                <dd>
                  <Link href={`/app/memory/${fact.id}`}>{fact.value}</Link>{" "}
                  <span className="memory-chip">{sourceLabel(fact.source_type)}</span>
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>
      <section className="panel">
        <h2>Recent runs</h2>
        {thread.recent_runs.length === 0 ? (
          <p className="muted-text">No runs yet. Choose this thread in an agent&apos;s test console or a team&apos;s run form.</p>
        ) : (
          <ul className="plain-list">
            {thread.recent_runs.map((run) => (
              <li key={run.id}>
                <Link href={run.kind === "agent" ? `/app/runs/${run.id}` : `/app/team-runs/${run.id}`}>
                  <span className="memory-chip">{run.kind}</span> {run.label}
                </Link>{" "}
                <StatusPill status={run.status} />{" "}
                <span className="muted-text">{formatDate(run.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="panel">
        <h2>Memory entries</h2>
        <MemoryTable entries={thread.memory} />
      </section>
      {!archived && (
        <section className="panel">
          <h2>Add thread memory</h2>
          <MemoryForm scope="thread" threadId={threadId} onCreated={reload} />
        </section>
      )}
    </>
  );
}
