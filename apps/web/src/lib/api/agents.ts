"use client";

import { authenticated, scoped } from "./auth";
import type { ExecutionInfo, JobStatus } from "./jobs";
import type { Citation, KnowledgeRetrieval } from "./knowledge";
import type { MemoryUsage } from "./memory";

export type AgentStatus = "draft" | "active" | "archived";
export type RunStatus =
  "queued" | "running" | "completed" | "failed" | "cancelled";
export type Intent =
  | "general"
  | "customer_lookup"
  | "calculation"
  | "system_status"
  | "memory_recall"
  | "knowledge_search";

export type Agent = {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description: string;
  instructions: string;
  status: AgentStatus;
  workspace_memory_enabled: boolean;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
};
export type AgentInput = {
  name: string;
  description: string;
  instructions: string;
};
export type AgentChanges = Partial<
  AgentInput & { status: AgentStatus; workspace_memory_enabled: boolean }
>;

export type RunError = { code: string; message: string };
export type ToolCall = {
  tool_key: string;
  tool_type: "internal" | "mcp";
  tool: string;
  status: "completed" | "failed";
  server_id: string | null;
  server_name: string | null;
  duration_ms: number | null;
};
export type RunResult = {
  run_id: string;
  agent_id: string;
  status: RunStatus;
  intent: Intent | null;
  summary: string | null;
  tools_used: string[];
  tool_calls: ToolCall[];
  duration_ms: number | null;
  step_count: number;
  error: RunError | null;
  created_at: string | null;
  execution: ExecutionInfo | null;
  thread_id: string | null;
};
export type RunSummary = {
  id: string;
  agent_id: string;
  created_by_user_id: string | null;
  agent_name: string;
  status: RunStatus;
  input_text: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  step_count: number;
  execution_status: JobStatus | null;
  thread_id: string | null;
};
export type RunEvent = {
  id: string;
  sequence: number;
  event_type:
    | "run_started"
    | "node_started"
    | "node_completed"
    | "node_failed"
    | "run_completed"
    | "run_failed"
    | "retry_scheduled"
    | "run_cancelled"
    | "memory_saved"
    | "memory_updated";
  node_name: string | null;
  status: "started" | "completed" | "failed";
  input_payload: Record<string, unknown> | null;
  output_payload: Record<string, unknown> | null;
  error_message: string | null;
  duration_ms: number | null;
  attempt: number | null;
  created_at: string;
};
export type RunDetail = RunSummary & {
  final_output: {
    intent: Intent;
    summary: string;
    tools_used: string[];
    provider: string;
    /** M9: structured citations for each [K#] in the summary. */
    citations?: Citation[];
  } | null;
  state: Record<string, unknown> | null;
  error: RunError | null;
  tool_calls: ToolCall[];
  events: RunEvent[];
  execution: ExecutionInfo | null;
  memory_context: MemoryUsage | null;
  /** M9: what knowledge_search retrieved for this run (null when it did not search). */
  knowledge?: KnowledgeRetrieval | null;
};

const id = (value: string) => encodeURIComponent(value);

export const listAgents = (organizationId: string, status?: AgentStatus) =>
  authenticated<Agent[]>(
    `/agents${status ? `?status=${status}` : ""}`,
    scoped(organizationId),
  );
export const getAgent = (organizationId: string, agentId: string) =>
  authenticated<Agent>(`/agents/${id(agentId)}`, scoped(organizationId));
export const createAgent = (organizationId: string, input: AgentInput) =>
  authenticated<Agent>(
    "/agents",
    scoped(organizationId, { method: "POST", body: JSON.stringify(input) }),
  );
export const updateAgent = (
  organizationId: string,
  agentId: string,
  changes: AgentChanges,
) =>
  authenticated<Agent>(
    `/agents/${id(agentId)}`,
    scoped(organizationId, { method: "PATCH", body: JSON.stringify(changes) }),
  );
export const runAgent = (
  organizationId: string,
  agentId: string,
  input: string,
  threadId?: string,
) =>
  authenticated<RunResult>(
    `/agents/${id(agentId)}/runs`,
    scoped(organizationId, {
      method: "POST",
      body: JSON.stringify(threadId ? { input, thread_id: threadId } : { input }),
    }),
  );
export const listRuns = (organizationId: string, agentId?: string) =>
  authenticated<RunSummary[]>(
    `/agent-runs${agentId ? `?agent_id=${id(agentId)}` : ""}`,
    scoped(organizationId),
  );
export const getRun = (organizationId: string, runId: string) =>
  authenticated<RunDetail>(`/agent-runs/${id(runId)}`, scoped(organizationId));

export type AgentToolAssignment = {
  id: string;
  agent_id: string;
  tool_key: string;
  tool_type: "internal" | "mcp";
  is_enabled: boolean;
  created_at: string;
};
export type ToolCatalogEntry = {
  tool_key: string;
  tool_type: "internal" | "mcp";
  name: string;
  description: string;
  server_name: string | null;
  is_enabled: boolean;
};

export const listToolCatalog = (organizationId: string) =>
  authenticated<ToolCatalogEntry[]>("/tools", scoped(organizationId));
export const listAgentTools = (organizationId: string, agentId: string) =>
  authenticated<AgentToolAssignment[]>(
    `/agents/${id(agentId)}/tools`,
    scoped(organizationId),
  );
export const assignAgentTool = (
  organizationId: string,
  agentId: string,
  toolKey: string,
) =>
  authenticated<AgentToolAssignment>(
    `/agents/${id(agentId)}/tools`,
    scoped(organizationId, {
      method: "POST",
      body: JSON.stringify({ tool_key: toolKey }),
    }),
  );
export const updateAgentTool = (
  organizationId: string,
  agentId: string,
  assignmentId: string,
  isEnabled: boolean,
) =>
  authenticated<AgentToolAssignment>(
    `/agents/${id(agentId)}/tools/${id(assignmentId)}`,
    scoped(organizationId, {
      method: "PATCH",
      body: JSON.stringify({ is_enabled: isEnabled }),
    }),
  );
export const removeAgentTool = (
  organizationId: string,
  agentId: string,
  assignmentId: string,
) =>
  authenticated<void>(
    `/agents/${id(agentId)}/tools/${id(assignmentId)}`,
    scoped(organizationId, { method: "DELETE" }),
  );
