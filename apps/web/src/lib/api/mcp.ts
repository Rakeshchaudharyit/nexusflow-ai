"use client";

import { authenticated, scoped } from "./auth";

export type McpTransport = "streamable_http";
export type McpServerStatus = "pending" | "connected" | "unavailable" | "disabled";

export type McpServer = {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description: string;
  transport: McpTransport;
  url: string;
  status: McpServerStatus;
  is_enabled: boolean;
  tool_count: number;
  created_by_user_id: string;
  last_connected_at: string | null;
  last_discovered_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
};
export type McpServerInput = {
  name: string;
  description: string;
  transport: McpTransport;
  url: string;
};
export type McpServerChanges = Partial<
  Pick<McpServer, "name" | "description" | "url" | "is_enabled">
>;
export type JsonSchema = {
  type?: string;
  properties?: Record<string, { type?: string; enum?: unknown[] }>;
  required?: string[];
};
export type McpTool = {
  id: string;
  mcp_server_id: string;
  name: string;
  tool_key: string;
  description: string;
  input_schema: JsonSchema;
  output_schema: JsonSchema | null;
  is_enabled: boolean;
  is_available: boolean;
  discovered_at: string;
};
export type McpConnectionTest = {
  status: "connected" | "unavailable";
  server: string | null;
  version: string | null;
  protocol_version: string | null;
  duration_ms: number;
  error: { code: string; message: string } | null;
};
export type McpDiscovery = {
  server: McpServer;
  tools: McpTool[];
  added: string[];
  updated: string[];
  removed: string[];
};

const id = (value: string) => encodeURIComponent(value);
const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

export const listMcpServers = (organizationId: string) =>
  authenticated<McpServer[]>("/mcp-servers", scoped(organizationId));
export const getMcpServer = (organizationId: string, serverId: string) =>
  authenticated<McpServer>(`/mcp-servers/${id(serverId)}`, scoped(organizationId));
export const createMcpServer = (organizationId: string, input: McpServerInput) =>
  authenticated<McpServer>("/mcp-servers", scoped(organizationId, json("POST", input)));
export const updateMcpServer = (
  organizationId: string,
  serverId: string,
  changes: McpServerChanges,
) =>
  authenticated<McpServer>(
    `/mcp-servers/${id(serverId)}`,
    scoped(organizationId, json("PATCH", changes)),
  );
export const testMcpServer = (organizationId: string, serverId: string) =>
  authenticated<McpConnectionTest>(
    `/mcp-servers/${id(serverId)}/test`,
    scoped(organizationId, { method: "POST" }),
  );
export const discoverMcpTools = (organizationId: string, serverId: string) =>
  authenticated<McpDiscovery>(
    `/mcp-servers/${id(serverId)}/discover`,
    scoped(organizationId, { method: "POST" }),
  );
export const listMcpTools = (organizationId: string, serverId: string) =>
  authenticated<McpTool[]>(`/mcp-servers/${id(serverId)}/tools`, scoped(organizationId));
export const toggleMcpTool = (
  organizationId: string,
  serverId: string,
  toolId: string,
  isEnabled: boolean,
) =>
  authenticated<McpTool>(
    `/mcp-servers/${id(serverId)}/tools/${id(toolId)}`,
    scoped(organizationId, json("PATCH", { is_enabled: isEnabled })),
  );
