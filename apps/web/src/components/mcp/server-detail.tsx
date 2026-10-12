"use client";

import { LoadingState } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback, useState } from "react";
import {
  describeError,
  formatDate,
  formatDuration,
  useResource,
} from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { useWorkspace } from "@/components/workspace-shell";
import {
  discoverMcpTools,
  getMcpServer,
  listMcpTools,
  testMcpServer,
  toggleMcpTool,
  updateMcpServer,
  type JsonSchema,
  type McpConnectionTest,
} from "@/lib/api/mcp";

function safeEndpoint(value: string): string {
  try { const url = new URL(value); url.username = ""; url.password = ""; url.search = ""; url.hash = ""; return url.toString(); } catch { return "Endpoint unavailable"; }
}

function schemaSummary(schema: JsonSchema): string {
  const properties = Object.entries(schema.properties ?? {});
  if (!properties.length) return "no arguments";
  const required = new Set(schema.required ?? []);
  return properties
    .map(([name, field]) => {
      const type = field.enum ? field.enum.join(" | ") : (field.type ?? "any");
      return `${name}${required.has(name) ? "" : "?"}: ${type}`;
    })
    .join(", ");
}

export function McpServerDetail({ serverId }: { serverId: string }) {
  const organization = useWorkspace();
  const loadServer = useCallback(
    () => getMcpServer(organization.id, serverId),
    [organization.id, serverId],
  );
  const loadTools = useCallback(
    () => listMcpTools(organization.id, serverId),
    [organization.id, serverId],
  );
  const server = useResource(loadServer);
  const tools = useResource(loadTools);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [connection, setConnection] = useState<McpConnectionTest | null>(null);
  const canManage = organization.role !== "member";

  async function act(action: () => Promise<string | null>) {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      setNotice(await action());
    } catch (failure) {
      setActionError(describeError(failure));
    } finally {
      setBusy(false);
      server.reload();
      tools.reload();
    }
  }
  const testConnection = () =>
    act(async () => {
      const result = await testMcpServer(organization.id, serverId);
      setConnection(result);
      return null;
    });
  const discover = () =>
    act(async () => {
      const result = await discoverMcpTools(organization.id, serverId);
      const parts = [
        `${result.tools.length} tools listed`,
        result.added.length && `added ${result.added.join(", ")}`,
        result.updated.length && `updated ${result.updated.join(", ")}`,
        result.removed.length && `no longer listed: ${result.removed.join(", ")}`,
      ];
      return `Discovery complete: ${parts.filter(Boolean).join("; ")}.`;
    });
  const setEnabled = (enabled: boolean) =>
    act(async () => {
      await updateMcpServer(organization.id, serverId, { is_enabled: enabled });
      return enabled ? "Server enabled." : "Server disabled.";
    });
  const setToolEnabled = (toolId: string, enabled: boolean) =>
    act(async () => {
      await toggleMcpTool(organization.id, serverId, toolId, enabled);
      return null;
    });

  if (server.loading) return <LoadingState />;
  const record = server.data;
  if (server.notFound || !record)
    return (
      <section className="panel narrow">
        <h1>{server.notFound ? "MCP server not found" : "Could not load this MCP server"}</h1>
        <p className="muted-text">
          {server.notFound
            ? `This MCP server does not exist in ${organization.name}.`
            : server.error}
        </p>
        <Link href="/app/mcp">Back to MCP servers</Link>
        {!server.notFound && (
          <button className="retry-button" onClick={server.reload}>
            Retry
          </button>
        )}
      </section>
    );
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">MCP / {organization.name}</p>
          <h1>{record.name}</h1>
        </div>
        <Link href="/app/mcp">Back to MCP servers</Link>
      </div>
      <section className="panel protocol-panel">
        <div className="protocol-band"><strong>MCP</strong><span>STREAMABLE HTTP</span><StatusPill status={record.status}/><span className="mono">mcp:{record.slug}:</span></div>
        <dl className="details">
          <dt>Status</dt>
          <dd>
            <StatusPill status={record.status} />
          </dd>
          <dt>Endpoint</dt>
          <dd className="mono">{safeEndpoint(record.url)}</dd>
          <dt>Transport</dt>
          <dd className="mono">Streamable HTTP</dd>
          <dt>Protocol</dt><dd className="mono">MCP</dd>
          <dt>Enabled</dt>
          <dd>{record.is_enabled ? "Yes" : "No"}</dd>
          <dt>Tool key prefix</dt>
          <dd className="mono">mcp:{record.slug}:</dd>
          <dt>Last connection</dt>
          <dd>{formatDate(record.last_connected_at)}</dd>
          <dt>Last discovery</dt>
          <dd>{formatDate(record.last_discovered_at)}</dd>
          {record.last_error_message && (
            <>
              <dt>Last error</dt>
              <dd>
                {record.last_error_message} ({record.last_error_code})
              </dd>
            </>
          )}
        </dl>
        {canManage && (
          <div className="button-row">
            <button disabled={busy || !record.is_enabled} onClick={testConnection}>
              Test Connection
            </button>
            <button disabled={busy || !record.is_enabled} onClick={discover}>
              Discover Tools
            </button>
            <button disabled={busy} onClick={() => setEnabled(!record.is_enabled)}>
              {record.is_enabled ? "Disable server" : "Enable server"}
            </button>
          </div>
        )}
        {busy && (
          <p className="muted-text" role="status">
            Contacting MCP server…
          </p>
        )}
        {connection && (
          <p
            className={connection.status === "connected" ? "notice" : "form-error"}
            role="status"
          >
            {connection.status === "connected"
              ? `Connected to ${connection.server ?? "server"} ${connection.version ?? ""} (protocol ${connection.protocol_version}) in ${formatDuration(connection.duration_ms)}.`
              : `Unavailable: ${connection.error?.message}`}
          </p>
        )}
        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}
        {actionError && (
          <p className="form-error" role="alert">
            {actionError}
          </p>
        )}
      </section>
      <section className="panel">
        <h2>Tool interface index</h2>
        {tools.error && <p className="form-error">{tools.error}</p>}
        {tools.data && tools.data.length === 0 && (
          <p className="muted-text">No tools discovered yet. Run discovery to list them.</p>
        )}
        {tools.data && tools.data.length > 0 && (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Tool</th>
                  <th>Description</th>
                  <th>Input schema</th>
                  <th>Enabled</th>
                </tr>
              </thead>
              <tbody>
                {tools.data.map((tool) => (
                  <tr key={tool.id}>
                    <td>
                      <span className="mono">{tool.name}</span>
                      {!tool.is_available && (
                        <span className="muted-text"> · no longer listed</span>
                      )}
                    </td>
                    <td className="muted-text">{tool.description || "—"}</td>
                    <td className="mono"><details className="schema-viewer"><summary>{schemaSummary(tool.input_schema)}</summary><pre className="payload">{JSON.stringify(tool.input_schema, null, 2)}</pre><span className="muted-text">{tool.tool_key}</span></details></td>
                    <td>
                      {canManage ? (
                        <label className="inline-toggle">
                          <input
                            type="checkbox"
                            checked={tool.is_enabled}
                            disabled={busy}
                            onChange={(event) =>
                              void setToolEnabled(tool.id, event.target.checked)
                            }
                          />
                          <span className="sr-only">Enable {tool.name}</span>
                        </label>
                      ) : tool.is_enabled ? (
                        "Yes"
                      ) : (
                        "No"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
