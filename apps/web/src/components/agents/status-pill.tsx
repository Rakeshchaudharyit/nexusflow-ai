import type { AgentStatus, RunStatus } from "@/lib/api/agents";
import type { JobStatus } from "@/lib/api/jobs";
import type { KnowledgeDocumentStatus, KnowledgeSourceStatus } from "@/lib/api/knowledge";
import type { McpServerStatus } from "@/lib/api/mcp";
import type { ThreadStatus } from "@/lib/api/memory";
import type {
  ActionStatus,
  ApprovalStatus,
  TeamRunStatus,
} from "@/lib/api/teams";

type Status =
  | AgentStatus
  | RunStatus
  | McpServerStatus
  | TeamRunStatus
  | ApprovalStatus
  | ActionStatus
  | JobStatus
  | ThreadStatus
  | KnowledgeSourceStatus
  | KnowledgeDocumentStatus
  | "inactive";

export function StatusPill({ status }: { status: Status }) {
  return (
    <span className={`status-pill status-${status}`}>
      <i aria-hidden="true" />{status.replaceAll("_", " ")}
    </span>
  );
}
