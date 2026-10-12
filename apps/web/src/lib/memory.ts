import type {
  MemoryEntry,
  MemoryScope,
  MemorySource,
  MemoryUsage,
} from "./api/memory";

const SOURCES: Record<MemorySource, string> = {
  manual_user_entry: "Manual",
  user_input: "User input",
  agent_run: "Agent run",
  team_run: "Team run",
  approved_action: "Approved action",
  thread_summary: "Thread summary",
};
const SCOPES: Record<MemoryScope, string> = {
  thread: "Thread",
  agent: "Agent",
  workspace: "Workspace",
};

export const sourceLabel = (source: MemorySource) => SOURCES[source];
export const scopeLabel = (scope: MemoryScope) => SCOPES[scope];

/** What to show for an entry in lists: "key = value" for facts, otherwise its text. */
export const memoryText = (entry: Pick<MemoryEntry, "fact_key" | "fact_value" | "summary" | "content">) =>
  entry.fact_key ? `${entry.fact_key} = ${entry.fact_value ?? ""}` : (entry.summary ?? entry.content);

/** Manual entries are deleted; entries derived from runs are deactivated (provenance kept). */
export const removalLabel = (entry: Pick<MemoryEntry, "source_type">) =>
  entry.source_type === "manual_user_entry" ? "Delete" : "Deactivate";

export const memoryStatus = (entry: Pick<MemoryEntry, "is_active" | "in_context">) =>
  !entry.is_active ? "inactive" : entry.in_context ? "active" : "expired";

/** Compact, count-only line for run detail: never the memory text. */
export function usageLine(usage: MemoryUsage | null | undefined): string | null {
  if (!usage) return null;
  const parts = [
    `Thread memory: ${usage.thread}`,
    `Agent memory: ${usage.agent}`,
    `Workspace memory: ${usage.workspace_enabled ? usage.workspace : "off"}`,
  ];
  if (usage.summary) parts.push("thread summary");
  if (usage.truncated) parts.push("budget reached");
  return parts.join(" · ");
}
