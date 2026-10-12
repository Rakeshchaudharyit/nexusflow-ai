"use client";

import { useCallback, useState, type FormEvent } from "react";
import { useWorkspace } from "@/components/workspace-shell";
import {
  assignAgentTool,
  listAgentTools,
  listToolCatalog,
  removeAgentTool,
  updateAgentTool,
} from "@/lib/api/agents";
import { describeError, useResource } from "./resource";

/** Tools this agent may call when it acts as a team member. */
export function AgentTools({
  agentId,
  onChanged,
}: {
  agentId: string;
  onChanged?: () => void;
}) {
  const organization = useWorkspace();
  const loadAssigned = useCallback(
    () => listAgentTools(organization.id, agentId),
    [organization.id, agentId],
  );
  const loadCatalog = useCallback(() => listToolCatalog(organization.id), [organization.id]);
  const assigned = useResource(loadAssigned);
  const catalog = useResource(loadCatalog);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canManage = organization.role !== "member";

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      assigned.reload();
      onChanged?.();
    } catch (failure) {
      setError(describeError(failure));
    } finally {
      setBusy(false);
    }
  }
  function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const key = String(new FormData(event.currentTarget).get("tool_key") ?? "");
    if (key) void act(() => assignAgentTool(organization.id, agentId, key));
  }

  const taken = new Set((assigned.data ?? []).map((item) => item.tool_key));
  const available = (catalog.data ?? []).filter((entry) => !taken.has(entry.tool_key));
  return (
    <section className="panel">
      <h2>Allowed tools</h2>
      <p className="field-hint">
        These permissions govern tool access when this agent works in a team.{" "}
        <span className="mono">internal:knowledge_search</span> also enables knowledge search
        in single runs, together with an assigned knowledge source.
      </p>
      {assigned.data && assigned.data.length === 0 && (
        <p className="muted-text">No tools assigned.</p>
      )}
      {assigned.data && assigned.data.length > 0 && (
        <ul className="plain-list">
          {assigned.data.map((item) => (
            <li key={item.id} className="tool-row">
              <div className="tool-entity"><span className="mono">{item.tool_key}</span><p>{catalog.data?.find(entry => entry.tool_key === item.tool_key)?.description}</p></div>
              <span className="muted-text">
                {item.tool_type === "mcp" ? "MCP" : "Internal"} ·{" "}
                {item.is_enabled ? "enabled" : "disabled"}
              </span>
              {canManage && (
                <span className="button-row">
                  <button
                    disabled={busy}
                    onClick={() =>
                      void act(() =>
                        updateAgentTool(organization.id, agentId, item.id, !item.is_enabled),
                      )
                    }
                  >
                    {item.is_enabled ? "Disable" : "Enable"}
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => void act(() => removeAgentTool(organization.id, agentId, item.id))}
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
            Assign tool
            <select name="tool_key" defaultValue="" required>
              <option value="" disabled>
                Choose a tool
              </option>
              {available.map((entry) => (
                <option key={entry.tool_key} value={entry.tool_key}>
                  {entry.tool_key}
                  {entry.server_name ? ` (${entry.server_name})` : ""}
                  {entry.is_enabled ? "" : " — disabled"}
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
