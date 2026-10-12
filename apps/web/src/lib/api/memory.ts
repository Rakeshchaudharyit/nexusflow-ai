"use client";

import { authenticated, scoped } from "./auth";
import type { TeamRunStatus } from "./teams";

export type MemoryType =
  | "thread_memory"
  | "agent_memory"
  | "workspace_memory"
  | "fact_memory"
  | "summary_memory";
export type MemoryScope = "thread" | "agent" | "workspace";
export type MemorySource =
  | "manual_user_entry"
  | "user_input"
  | "agent_run"
  | "team_run"
  | "approved_action"
  | "thread_summary";
export type ThreadStatus = "active" | "archived";

/** Mirrors the API's MemoryResponse. */
export type MemoryEntry = {
  id: string;
  organization_id: string;
  memory_type: MemoryType;
  scope: MemoryScope;
  thread_id: string | null;
  agent_id: string | null;
  team_id: string | null;
  fact_key: string | null;
  fact_value: string | null;
  confidence: number | null;
  content: string;
  summary: string | null;
  importance: number;
  pinned: boolean;
  source_type: MemorySource;
  source_id: string | null;
  created_by_user_id: string | null;
  expires_at: string | null;
  is_active: boolean;
  deactivated_at: string | null;
  created_at: string;
  updated_at: string;
  in_context: boolean;
  thread_title: string | null;
  agent_name: string | null;
};
export type Thread = {
  id: string;
  organization_id: string;
  created_by_user_id: string;
  title: string;
  status: ThreadStatus;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
  agent_run_count: number;
  team_run_count: number;
  memory_count: number;
};
export type ThreadDetail = Thread & {
  summary: string | null;
  facts: {
    id: string;
    key: string;
    value: string;
    confidence: number | null;
    source_type: MemorySource;
    updated_at: string;
  }[];
  memory: MemoryEntry[];
  recent_runs: {
    kind: "agent" | "team";
    id: string;
    status: TeamRunStatus;
    label: string;
    created_at: string;
  }[];
};
/** Count-only record of the memory a run received (never the memory text). */
export type MemoryUsage = {
  thread: number;
  agent: number;
  workspace: number;
  facts: number;
  summary: boolean;
  workspace_enabled: boolean;
  chars: number;
  truncated: boolean;
  entry_ids: string[];
};
export type MemoryFilters = {
  memory_type?: MemoryType;
  scope?: MemoryScope;
  thread_id?: string;
  agent_id?: string;
  active?: boolean;
  source_type?: MemorySource;
  limit?: number;
};
export type MemoryInput = {
  scope: MemoryScope;
  thread_id?: string;
  agent_id?: string;
  fact_key?: string;
  fact_value?: string;
  content?: string;
  importance?: number;
  pinned?: boolean;
  expires_at?: string | null;
};
export type MemoryChanges = Partial<{
  content: string;
  fact_value: string;
  importance: number;
  pinned: boolean;
  expires_at: string | null;
  is_active: boolean;
}>;

const id = (value: string) => encodeURIComponent(value);
const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});
const query = (filters: Record<string, unknown>) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters))
    if (value !== undefined && value !== "") params.set(key, String(value));
  return params.size ? `?${params}` : "";
};

export const listThreads = (organizationId: string, status?: ThreadStatus) =>
  authenticated<Thread[]>(`/threads${query({ status })}`, scoped(organizationId));
export const createThread = (organizationId: string, title: string) =>
  authenticated<Thread>("/threads", scoped(organizationId, json("POST", { title })));
export const getThread = (organizationId: string, threadId: string) =>
  authenticated<ThreadDetail>(`/threads/${id(threadId)}`, scoped(organizationId));
export const updateThread = (
  organizationId: string,
  threadId: string,
  changes: { title?: string; status?: ThreadStatus },
) =>
  authenticated<Thread>(
    `/threads/${id(threadId)}`,
    scoped(organizationId, json("PATCH", changes)),
  );
export const listMemory = (organizationId: string, filters: MemoryFilters = {}) =>
  authenticated<MemoryEntry[]>(`/memory${query(filters)}`, scoped(organizationId));
export const getMemory = (organizationId: string, memoryId: string) =>
  authenticated<MemoryEntry>(`/memory/${id(memoryId)}`, scoped(organizationId));
export const createMemory = (organizationId: string, input: MemoryInput) =>
  authenticated<MemoryEntry>("/memory", scoped(organizationId, json("POST", input)));
export const updateMemory = (
  organizationId: string,
  memoryId: string,
  changes: MemoryChanges,
) =>
  authenticated<MemoryEntry>(
    `/memory/${id(memoryId)}`,
    scoped(organizationId, json("PATCH", changes)),
  );
export const deleteMemory = (organizationId: string, memoryId: string) =>
  authenticated<{ id: string; outcome: "deleted" | "deactivated" }>(
    `/memory/${id(memoryId)}`,
    scoped(organizationId, { method: "DELETE" }),
  );
