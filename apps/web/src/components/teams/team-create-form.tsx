"use client";

import { LoadingState } from "@/components/ui/design-system";

import Link from "next/link";
import { ManagersOnly } from "@/components/managers-only";
import { useRouter } from "next/navigation";
import { useCallback, useState, type FormEvent } from "react";
import { describeError, useResource } from "@/components/agents/resource";
import { useWorkspace } from "@/components/workspace-shell";
import { listAgents } from "@/lib/api/agents";
import { createTeam, type TeamMemberInput, type TeamRole } from "@/lib/api/teams";
import { ROLE_LABELS, ROLES } from "./roles";

export function TeamCreateForm() {
  const organization = useWorkspace();
  const router = useRouter();
  const load = useCallback(() => listAgents(organization.id), [organization.id]);
  const agents = useResource(load);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    const members: TeamMemberInput[] = ROLES.flatMap((role, position) => {
      const agentId = String(data.get(`agent-${role}`) ?? "");
      return agentId
        ? [{ agent_id: agentId, role, position, is_required: data.get(`required-${role}`) === "on" }]
        : [];
    });
    setBusy(true);
    setError(null);
    try {
      const team = await createTeam(organization.id, {
        name: String(data.get("name") ?? "").trim(),
        description: String(data.get("description") ?? "").trim(),
        members,
      });
      router.push(`/app/teams/${team.id}`);
    } catch (failure) {
      setError(describeError(failure));
      setBusy(false);
    }
  }

  const options = (agents.data ?? []).filter((agent) => agent.status !== "archived");
  if (organization.role === "member")
    return (
      <ManagersOnly action="create teams" backHref="/app/teams" backLabel="Back to teams" />
    );
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">TEAMS / {organization.name}</p>
          <h1>Create team</h1>
        </div>
        <Link href="/app/teams">Back to teams</Link>
      </div>
      <form className="panel narrow" onSubmit={submit}>
        <label>
          Name
          <input
            name="name"
            required
            maxLength={120}
            pattern=".*\S.*"
            defaultValue="Enterprise Account Intelligence Team"
          />
        </label>
        <label>
          Description
          <input
            name="description"
            maxLength={500}
            defaultValue="Supervisor-led account research, analysis and recommendation."
          />
        </label>
        <h2>Members</h2>
        <p className="field-hint">
          Pick an agent for each role. A runnable team needs a supervisor, at least one
          specialist, a writer and a validator. Agents are scoped to this workspace.
        </p>
        {agents.loading && <LoadingState />}
        {ROLES.map((role: TeamRole) => (
          <div key={role} className="role-row">
            <label>
              {ROLE_LABELS[role]}
              <select name={`agent-${role}`} defaultValue="">
                <option value="">Not in team</option>
                {options.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name}
                    {agent.status === "draft" ? " (draft)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <label className="inline-toggle">
              <input
                type="checkbox"
                name={`required-${role}`}
                aria-label={`${ROLE_LABELS[role]} required`}
                defaultChecked
              />
              Required
            </label>
          </div>
        ))}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="primary-button" disabled={busy}>
          {busy ? "Creating…" : "Create team"}
        </button>
      </form>
    </>
  );
}
