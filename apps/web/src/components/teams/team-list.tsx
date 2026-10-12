"use client";

import { LoadingState } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback } from "react";
import { formatDate, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { useWorkspace } from "@/components/workspace-shell";
import { roleLabel } from "./roles";
import { Icon, EmptyState } from "../ui/design-system";
import { listTeams, getTeam } from "@/lib/api/teams";

export function TeamList() {
  const organization = useWorkspace();
  const load = useCallback(async () => {
    const teams = await listTeams(organization.id);
    return Promise.all(teams.map(async team => {
      try { return { ...team, members: (await getTeam(organization.id, team.id)).members }; }
      catch { return { ...team, members: [] }; }
    }));
  }, [organization.id]);
  const { data: teams, error, loading } = useResource(load);
  const canManage = organization.role !== "member";
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">TEAMS / {organization.name}</p>
          <h1>Agent teams</h1>
        </div>
        {canManage && (
          <Link className="primary-button" href="/app/teams/new">
            Create team
          </Link>
        )}
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {loading && <LoadingState />}
      {teams && teams.length === 0 && (
        <EmptyState title="Orchestrate your first team" description="Combine specialist agents under a supervisor." href={canManage ? "/app/teams/new" : "/app/agents"} action={canManage ? "Create team" : "Explore agents"} />
      )}
      {teams && teams.length > 0 && (
        <div className="resource-card-grid">
          {teams.map(team => <section className="panel team-card" key={team.id}>
            <div className="resource-card-heading"><span className="resource-icon"><Icon name="team" /></span><StatusPill status={team.status}/></div>
            <h2><Link href={`/app/teams/${team.id}`}>{team.name}</Link></h2>
            <p className="muted-text">{team.description || "A coordinated team of agents with shared context."}</p>
            <div className="team-sequence">{team.members.map(member => <span key={member.id}>{roleLabel(member.role)}</span>)}</div>
            <div className="card-footer"><span>{team.member_count} agents · Updated {formatDate(team.updated_at)}</span><Link href={`/app/teams/${team.id}#run`}>{team.status === "active" ? "Run Team →" : "Open Team →"}</Link></div>
          </section>)}
        </div>
      )}
    </>
  );
}
