"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { describeError, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { useWorkspace } from "@/components/workspace-shell";
import { listAgentTools } from "@/lib/api/agents";
import {
  assignAgentKnowledge,
  listAgentKnowledge,
  listSources,
  removeAgentKnowledge,
  updateAgentKnowledge,
} from "@/lib/api/knowledge";
import { assignable } from "@/lib/knowledge";

const TOOL = "internal:knowledge_search";

/** Knowledge sources this agent may search. Effective only together with the
 * internal:knowledge_search tool; both grants are checked by the server at run time. */
export function AgentKnowledge({
  agentId,
  toolsVersion = 0,
}: {
  agentId: string;
  /** Bumped when the agent's tool assignments change, so the tool check stays current. */
  toolsVersion?: number;
}) {
  const organization = useWorkspace();
  const loadGrants = useCallback(
    () => listAgentKnowledge(organization.id, agentId),
    [organization.id, agentId],
  );
  const loadSources = useCallback(() => listSources(organization.id), [organization.id]);
  const loadTools = useCallback(
    () => listAgentTools(organization.id, agentId),
    [organization.id, agentId],
  );
  const grants = useResource(loadGrants);
  const sources = useResource(loadSources);
  const tools = useResource(loadTools);
  const reloadTools = tools.reload;
  useEffect(() => {
    if (toolsVersion) reloadTools();
  }, [toolsVersion, reloadTools]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canManage = organization.role !== "member";

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      grants.reload();
      sources.reload();
    } catch (failure) {
      setError(describeError(failure));
    } finally {
      setBusy(false);
    }
  }
  function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const sourceId = String(new FormData(event.currentTarget).get("source_id") ?? "");
    if (sourceId) void act(() => assignAgentKnowledge(organization.id, agentId, sourceId));
  }

  const tool = tools.data?.find((item) => item.tool_key === TOOL);
  const taken = new Set((grants.data ?? []).map((grant) => grant.source_id));
  const available = (sources.data ?? []).filter(
    (source) => !taken.has(source.id) && assignable(source.status),
  );
  return (
    <section className="panel">
      <h2>Knowledge sources</h2>
      <p className="field-hint">
        The agent searches these sources with <span className="mono">{TOOL}</span> and cites what
        it uses. It needs both the tool (above) and at least one enabled source.
        {tools.data && (!tool || !tool.is_enabled) && (
          <strong> The knowledge_search tool is not {tool ? "enabled" : "assigned"} yet.</strong>
        )}
      </p>
      {grants.data && grants.data.length === 0 && (
        <p className="muted-text">No knowledge sources assigned.</p>
      )}
      {grants.data && grants.data.length > 0 && (
        <ul className="plain-list">
          {grants.data.map((grant) => (
            <li key={grant.id} className="tool-row">
              <div className="tool-entity">
                <Link href={`/app/knowledge/${grant.source_id}`}>{grant.source_name}</Link>
                <p className="mono">
                  {grant.document_count} documents · {grant.chunk_count} chunks
                </p>
              </div>
              <span className="muted-text">
                <StatusPill status={grant.source_status} /> ·{" "}
                {grant.is_enabled ? "enabled" : "disabled"}
              </span>
              {canManage && (
                <span className="button-row">
                  <button
                    disabled={busy || (!grant.is_enabled && !assignable(grant.source_status))}
                    onClick={() =>
                      void act(() =>
                        updateAgentKnowledge(
                          organization.id,
                          agentId,
                          grant.source_id,
                          !grant.is_enabled,
                        ),
                      )
                    }
                  >
                    {grant.is_enabled ? "Disable" : "Enable"}
                  </button>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void act(() => removeAgentKnowledge(organization.id, agentId, grant.source_id))
                    }
                  >
                    Remove
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <form onSubmit={assign} className="inline-form">
          <label>
            Assign source
            <select name="source_id" defaultValue="" required>
              <option value="" disabled>
                Choose a knowledge source
              </option>
              {available.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name} ({source.status}, {source.chunk_count} chunks)
                </option>
              ))}
            </select>
          </label>
          <button disabled={busy || !available.length}>Assign</button>
        </form>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
