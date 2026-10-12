"use client";

import { LoadingState, EmptyState } from "@/components/ui/design-system";

import Link from "next/link";
import { useCallback } from "react";
import { formatDate, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { useWorkspace } from "@/components/workspace-shell";
import { listMcpServers } from "@/lib/api/mcp";

export function McpServerList() {
  const organization = useWorkspace();
  const load = useCallback(() => listMcpServers(organization.id), [organization.id]);
  const { data: servers, error, loading } = useResource(load);
  const canManage = organization.role !== "member";
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">MCP / {organization.name}</p>
          <h1>MCP servers</h1>
        </div>
        {canManage && (
          <Link className="primary-button" href="/app/mcp/new">
            Add server
          </Link>
        )}
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {loading && <LoadingState />}
      {servers && servers.length === 0 && (
        <EmptyState title="Connect your tool infrastructure" description="Discover MCP tools and give agents controlled access." href={canManage ? "/app/mcp/new" : "/app"} action={canManage ? "Register MCP server" : "Back to dashboard"} />
      )}
      {servers && servers.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Transport</th>
                <th>Tools</th>
                <th>Last connected</th>
                <th>Last discovered</th>
                <th>Enabled</th>
              </tr>
            </thead>
            <tbody>
              {servers.map((server) => (
                <tr key={server.id}>
                  <td>
                    <Link href={`/app/mcp/${server.id}`}>{server.name}</Link>
                  </td>
                  <td>
                    <StatusPill status={server.status} />
                  </td>
                  <td className="mono">{server.transport}</td>
                  <td>{server.tool_count}</td>
                  <td className="nowrap">{formatDate(server.last_connected_at)}</td>
                  <td className="nowrap">{formatDate(server.last_discovered_at)}</td>
                  <td>{server.is_enabled ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
