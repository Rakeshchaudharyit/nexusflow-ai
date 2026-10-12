"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { describeError } from "@/components/agents/resource";
import { ManagersOnly } from "@/components/managers-only";
import { useWorkspace } from "@/components/workspace-shell";
import { createSource, type KnowledgeSourceType } from "@/lib/api/knowledge";

export function SourceCreateForm() {
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
      const source = await createSource(organization.id, {
        name: String(data.get("name") ?? "").trim(),
        description: String(data.get("description") ?? "").trim(),
        source_type: String(data.get("source_type") ?? "file") as KnowledgeSourceType,
      });
      router.push(`/app/knowledge/${source.id}`);
    } catch (failure) {
      setError(describeError(failure));
      setBusy(false);
    }
  }

  if (organization.role === "member")
    return (
      <ManagersOnly
        action="create knowledge sources"
        backHref="/app/knowledge"
        backLabel="Back to knowledge"
      />
    );
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">KNOWLEDGE / {organization.name}</p>
          <h1>New knowledge source</h1>
        </div>
        <Link href="/app/knowledge">Back to knowledge</Link>
      </div>
      <form className="panel narrow" onSubmit={submit}>
        <label>
          Name
          <input
            name="name"
            required
            maxLength={120}
            pattern=".*\S.*"
            placeholder="Enterprise Security Knowledge"
          />
        </label>
        <label>
          Description
          <input name="description" maxLength={1000} placeholder="What these documents cover" />
        </label>
        <label>
          Source type
          <select name="source_type" defaultValue="file">
            <option value="file">Files (.txt, .md, .pdf, .docx)</option>
            <option value="text">Pasted text</option>
          </select>
        </label>
        <label>
          Embedding provider
          <select name="embedding_provider" defaultValue="deterministic_local" disabled>
            <option value="deterministic_local">deterministic_local · 384 dimensions</option>
          </select>
        </label>
        <p className="field-hint">
          The local provider is deterministic and offline (demo and tests). Production
          deployments configure a real embedding model on the server.
        </p>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="primary-button" disabled={busy}>
          {busy ? "Creating…" : "Create Source"}
        </button>
      </form>
    </>
  );
}
