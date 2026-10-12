"use client";

import { LoadingState } from "@/components/ui/design-system";

import { identityCode } from "../ui/nexusflow-brand";
import Link from "next/link";
import { useCallback } from "react";
import { useWorkspace } from "@/components/workspace-shell";
import { EmptyState } from "../ui/design-system";
import { listAgents, listAgentTools } from "@/lib/api/agents";
import { formatDate, useResource } from "./resource";
import { StatusPill } from "./status-pill";

export function AgentList() {
  const organization = useWorkspace();
  const load = useCallback(async () => {
    const agents = await listAgents(organization.id);
    return Promise.all(agents.map(async agent => {
      try { return { ...agent, tools: await listAgentTools(organization.id, agent.id) }; }
      catch { return { ...agent, tools: null }; }
    }));
  }, [organization.id]);
  const { data: agents, error, loading } = useResource(load);
  const canManage = organization.role !== "member";
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">AGENTS / {organization.name}</p>
          <h1>Agents</h1>
        </div>
        {canManage && (
          <Link className="primary-button" href="/app/agents/new">
            Create agent
          </Link>
        )}
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {loading && <LoadingState />}
      {agents && agents.length === 0 && (
        <EmptyState title="Build your first agent" description="Configure instructions and assign controlled tool access." href={canManage ? "/app/agents/new" : "/app"} action={canManage ? "Create agent" : "Back to dashboard"} />
      )}
      {agents && agents.length > 0 && (
        <div className="resource-card-grid">
          {agents.map(agent => <section className="panel agent-card" key={agent.id}>
            <div className="resource-card-heading"><span className="agent-code">{identityCode(agent.name)}</span><StatusPill status={agent.status}/></div>
            <h2><Link href={`/app/agents/${agent.id}`}>{agent.name}</Link></h2>
            <p className="muted-text">{agent.description || "No description provided."}</p>
            <div className="agent-tool-index"><span className="eyebrow">TOOL ACCESS</span>{agent.tools ? agent.tools.filter(t=>t.is_enabled).length ? agent.tools.filter(t=>t.is_enabled).map(tool=><span className="mono" key={tool.id}>{tool.tool_type === "mcp" ? "MCP" : "INT"} · {tool.tool_key.split(":").at(-1)}</span>) : <span className="muted-text">No enabled tools</span> : <span>Tool assignments unavailable</span>}</div>
            <div className="card-footer"><span>Updated {formatDate(agent.updated_at)}</span><Link href={`/app/agents/${agent.id}`}>Open →</Link></div>
          </section>)}
        </div>
      )}
    </>
  );
}
