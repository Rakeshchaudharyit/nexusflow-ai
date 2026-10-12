"use client";

import Link from "next/link";
import { ManagersOnly } from "@/components/managers-only";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { describeError } from "@/components/agents/resource";
import { useWorkspace } from "@/components/workspace-shell";
import { createMcpServer } from "@/lib/api/mcp";

export function McpServerCreateForm() {
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
      const server = await createMcpServer(organization.id, {
        name: String(data.get("name") ?? "").trim(),
        description: String(data.get("description") ?? "").trim(),
        transport: "streamable_http",
        url: String(data.get("url") ?? "").trim(),
      });
      router.push(`/app/mcp/${server.id}`);
    } catch (failure) {
      setError(describeError(failure));
      setBusy(false);
    }
  }
  if (organization.role === "member")
    return (
      <ManagersOnly action="register MCP servers" backHref="/app/mcp" backLabel="Back to MCP servers" />
    );
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">MCP / {organization.name}</p>
          <h1>Add MCP server</h1>
        </div>
        <Link href="/app/mcp">Back to MCP servers</Link>
      </div>
      <form className="panel narrow" onSubmit={submit}>
        <label>
          Name
          <input
            name="name"
            required
            maxLength={120}
            pattern=".*\S.*"
            defaultValue="NexusFlow Demo Tools"
          />
        </label>
        <label>
          Description
          <input
            name="description"
            maxLength={500}
            defaultValue="Internal demonstration MCP server"
          />
        </label>
        <label>
          Transport
          <select name="transport" defaultValue="streamable_http">
            <option value="streamable_http">Streamable HTTP</option>
          </select>
        </label>
        <label>
          URL
          <input
            name="url"
            required
            maxLength={2048}
            defaultValue="http://mcp-demo:8765/mcp"
            inputMode="url"
          />
        </label>
        <p className="field-hint">
          Only hosts on the server&apos;s MCP allowlist are accepted. Private,
          loopback and metadata addresses are rejected.
        </p>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <button className="primary-button" disabled={busy}>
          {busy ? "Adding…" : "Add server"}
        </button>
      </form>
    </>
  );
}
