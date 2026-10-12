import Link from "next/link";
import type { ToolCall } from "@/lib/api/agents";
import { formatDuration } from "./resource";
import { StatusPill } from "./status-pill";

export function ToolCalls({ calls }: { calls: ToolCall[] }) {
  if (!calls.length) return <p className="muted-text">No tools were called.</p>;
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Tool type</th>
            <th>Server</th>
            <th>Tool</th>
            <th>Duration</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((call, index) => (
            <tr key={`${call.tool_key}-${index}`}>
              <td className="mono">{call.tool_type === "mcp" ? "MCP" : "Internal"}</td>
              <td>
                {call.server_id ? (
                  <Link href={`/app/mcp/${call.server_id}`}>{call.server_name}</Link>
                ) : (
                  "NexusFlow"
                )}
              </td>
              <td className="mono" title={call.tool_key}>
                {call.tool}
              </td>
              <td className="nowrap">{formatDuration(call.duration_ms)}</td>
              <td>
                <StatusPill status={call.status === "completed" ? "completed" : "failed"} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
