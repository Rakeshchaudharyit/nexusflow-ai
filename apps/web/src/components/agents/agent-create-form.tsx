"use client";

import Link from "next/link";
import { ManagersOnly } from "@/components/managers-only";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useWorkspace } from "@/components/workspace-shell";
import { createAgent } from "@/lib/api/agents";
import { describeError } from "./resource";

export function AgentCreateForm() {
  const organization = useWorkspace();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const agent = await createAgent(organization.id, {
        name: String(data.get("name") ?? "").trim(),
        description: String(data.get("description") ?? "").trim(),
        instructions: String(data.get("instructions") ?? "").trim(),
      });
      router.push(`/app/agents/${agent.id}`);
    } catch (failure) {
      setError(describeError(failure));
      setBusy(false);
    }
  }
  if (organization.role === "member")
    return (
      <ManagersOnly action="create agents" backHref="/app/agents" backLabel="Back to agents" />
    );
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">AGENTS / {organization.name}</p>
          <h1>Create agent</h1>
        </div>
        <Link href="/app/agents">Back to agents</Link>
      </div>
      <form className="panel narrow" onSubmit={submit}>
        <label>
          Name
          <input name="name" required maxLength={120} pattern=".*\S.*" />
        </label>
        <label>
          Description
          <input name="description" maxLength={500} />
        </label>
        <label>
          Instructions
          <textarea name="instructions" required maxLength={4000} rows={5} />
        </label>
        <p className="field-hint">
          New agents start as drafts. Activate an agent before running it.
        </p>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="primary-button" disabled={busy}>
          {busy ? "Creating…" : "Create Agent"}
        </button>
      </form>
    </>
  );
}
