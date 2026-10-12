"use client";

import { useState, type FormEvent } from "react";
import { describeError } from "@/components/agents/resource";
import { useWorkspace } from "@/components/workspace-shell";
import { createMemory, type MemoryScope } from "@/lib/api/memory";

/** Manual memory: a note, or a key/value fact. Members may add thread memory only. */
export function MemoryForm({
  scope,
  threadId,
  agentId,
  onCreated,
}: {
  scope: MemoryScope;
  threadId?: string;
  agentId?: string;
  onCreated: () => void;
}) {
  const organization = useWorkspace();
  const [kind, setKind] = useState<"note" | "fact">("note");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const value = (name: string) => String(data.get(name) ?? "").trim();
    setBusy(true);
    setFailure(null);
    try {
      await createMemory(organization.id, {
        scope,
        thread_id: threadId,
        agent_id: agentId,
        importance: Number(value("importance") || 3),
        ...(kind === "fact"
          ? { fact_key: value("fact_key"), fact_value: value("fact_value") }
          : { content: value("content") }),
        ...(value("expires_at") ? { expires_at: new Date(value("expires_at")).toISOString() } : {}),
      });
      form.reset();
      onCreated();
    } catch (problem) {
      setFailure(describeError(problem));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="filter-row">
        <label>
          Kind
          <select value={kind} onChange={(event) => setKind(event.target.value as "note" | "fact")}>
            <option value="note">Note</option>
            <option value="fact">Fact (key = value)</option>
          </select>
        </label>
        <label>
          Importance
          <select name="importance" defaultValue="3">
            {[1, 2, 3, 4, 5].map((level) => <option key={level} value={level}>{level}</option>)}
          </select>
        </label>
        <label>
          Expires (optional)
          <input type="date" name="expires_at" />
        </label>
      </div>
      {kind === "note" ? (
        <label>
          Note
          <textarea name="content" required maxLength={2000} rows={2}
            placeholder="Acme Corporation prefers structured executive summaries." />
        </label>
      ) : (
        <div className="filter-row">
          <label>
            Key
            <input name="fact_key" required maxLength={80} pattern="[a-z][a-z0-9_]*" placeholder="account_owner" />
          </label>
          <label>
            Value
            <input name="fact_value" required maxLength={500} placeholder="Maya Chen" />
          </label>
        </div>
      )}
      <p className="field-hint">Memory is reference context for runs. It never changes policies, permissions or tools. Do not store passwords or keys.</p>
      {failure && <p className="form-error" role="alert">{failure}</p>}
      <button className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save memory"}</button>
    </form>
  );
}
