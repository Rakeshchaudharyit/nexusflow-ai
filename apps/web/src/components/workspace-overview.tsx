"use client";
import { displayStatus } from "@/lib/jobs";

import { actionLabel } from "@/lib/actions";
import Link from "next/link";
import { useCallback } from "react";
import { useWorkspace } from "./workspace-shell";
import { listAgents, listRuns, listToolCatalog } from "@/lib/api/agents";
import { listTeams, listTeamRuns } from "@/lib/api/teams";
import { listMcpServers } from "@/lib/api/mcp";
import { listApprovals } from "@/lib/api/approvals";
import { useResource, formatDate, formatDuration } from "./agents/resource";
import { StatusPill } from "./agents/status-pill";
import { FoundationStatus } from "./foundation-status";
import { EmptyState, LoadingState, PageHeader, SectionCard } from "./ui/design-system";

export function WorkspaceOverview() {
  const organization = useWorkspace();
  const load = useCallback(async () => {
    const [agents, teams, servers, tools, runs, teamRuns, approvals] = await Promise.all([
      listAgents(organization.id), listTeams(organization.id), listMcpServers(organization.id),
      listToolCatalog(organization.id), listRuns(organization.id), listTeamRuns(organization.id),
      listApprovals(organization.id, { status: "pending" }),
    ]);
    return { agents, teams, servers, tools, runs, teamRuns, approvals };
  }, [organization.id]);
  const { data, error, loading, reload } = useResource(load);
  const recent = data ? [
    ...data.runs.map(run => ({ ...run, name: run.agent_name, input: run.input_text, kind: "Agent", href: `/app/runs/${run.id}` })),
    ...data.teamRuns.map(run => ({ ...run, name: run.team_name, input: run.objective, kind: "Team", href: `/app/team-runs/${run.id}` })),
  ].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 4) : [];
  return <>
    <PageHeader eyebrow="01 / OPERATIONS CONTROL" title="Control plane" description="Build, orchestrate and observe your agent infrastructure." actions={<Link className="primary-button" href={organization.role === "member" ? "/app/agents" : "/app/agents/new"}>{organization.role === "member" ? "Explore agents" : "+ Create agent"}</Link>} />
    {error && <p className="form-error" role="alert">{error}<button onClick={reload} className="retry-button">Retry</button></p>}
    {loading && <LoadingState />}
    {data && <nav className="operations-strip" aria-label="Operational counters">
      <Link href="/app/agents"><span>ACTIVE</span><strong>{String(data.agents.filter(a=>a.status === "active").length).padStart(2,"0")}</strong><small>agents</small></Link>
      <Link href="/app/teams"><span>TEAMS</span><strong>{String(data.teams.length).padStart(2,"0")}</strong><small>configured</small></Link>
      <Link href="/app/mcp"><span>TOOLS</span><strong>{String(data.tools.filter(t=>t.tool_type === "mcp" && t.is_enabled).length).padStart(2,"0")}</strong><small>MCP</small></Link>
      <Link href="/app/approvals"><span>APPROVALS</span><strong>{String(data.approvals.length).padStart(2,"0")}</strong><small>pending</small></Link>
      <div><span>CONNECTIONS</span><strong>{data.servers.filter(s=>s.status === "connected").length}<small> / {data.servers.length}</small></strong><small>servers connected</small></div>
    </nav>}
    <div className="dashboard-grid">
      <SectionCard title="Recent executions">
        <div className="section-caption"><span>Agent and team activity</span><Link href="/app/team-runs">All team runs →</Link></div>
        {recent.length ? <div className="activity-list">{recent.map(run => <Link className="activity-row" href={run.href} key={run.id}>
          <div className="activity-icon">{run.kind === "Team" ? "⇄" : "↳"}</div><div className="activity-copy"><strong>{run.name}</strong><p>{run.input}</p><span>{run.kind} run · {formatDate(run.created_at)}</span></div><div className="activity-state"><StatusPill status={displayStatus(run.status, run.execution_status)} /><span>{formatDuration(run.duration_ms)}</span></div>
        </Link>)}</div> : !loading && <EmptyState title="Your execution history starts here" description="Run an agent or team to inspect its work and tool calls." href="/app/agents" action="Explore agents" />}
      </SectionCard>
      <div className="dashboard-side"><FoundationStatus compact />
        <SectionCard title="Decision queue"><div className="oversight-count">{data?.approvals.length ?? "—"}<span>pending decisions</span></div><p className="muted-text">Review proposed actions before they execute.</p>{data?.approvals.slice(0,2).map(approval => <Link className="pending-review" key={approval.id} href={`/app/approvals/${approval.id}`}><strong>{actionLabel(approval.action_type)}</strong><span>{approval.team_name} · {formatDate(approval.created_at)}</span><StatusPill status={approval.status}/></Link>)}<Link className="secondary-button" href="/app/approvals">Open approval inbox →</Link></SectionCard>
      </div>
    </div>
    {data && <SectionCard title="Agent network" className="network-panel"><div className="network-index">{data.agents.map((agent,index)=><Link key={agent.id} href={`/app/agents/${agent.id}`}><span className="mono">{String(index+1).padStart(2,"0")}</span><strong>{agent.name}</strong><StatusPill status={agent.status}/></Link>)}</div></SectionCard>}
    {data && <SectionCard title="MCP infrastructure"><div className="infrastructure-list">{data.servers.length ? data.servers.map(server => <Link href={`/app/mcp/${server.id}`} key={server.id}><span className="mono">{server.name}</span><span>{server.tool_count} tools</span><StatusPill status={server.status} /></Link>) : <EmptyState title="Connect your tools" description="Register an MCP server to discover tools for your agents." href="/app/mcp" action="Manage MCP servers" />}</div></SectionCard>}
  </>;
}
