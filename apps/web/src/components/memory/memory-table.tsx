import Link from "next/link";
import { formatDate, preview } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import type { MemoryEntry } from "@/lib/api/memory";
import { memoryStatus, memoryText, scopeLabel, sourceLabel } from "@/lib/memory";

export function MemoryTable({ entries }: { entries: MemoryEntry[] }) {
  if (!entries.length) return <p className="muted-text">No memory entries.</p>;
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th>Memory</th>
            <th>Type</th>
            <th>Scope</th>
            <th>Source</th>
            <th>Created</th>
            <th>Expires</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <tr key={entry.id}>
              <td>
                <Link href={`/app/memory/${entry.id}`}>{preview(memoryText(entry), 90)}</Link>
                {entry.pinned && <> <span className="memory-chip">pinned</span></>}
              </td>
              <td><span className="memory-chip">{entry.memory_type.replace("_memory", "")}</span></td>
              <td>{scopeLabel(entry.scope)}</td>
              <td>{sourceLabel(entry.source_type)}</td>
              <td className="nowrap">{formatDate(entry.created_at)}</td>
              <td className="nowrap">{formatDate(entry.expires_at)}</td>
              <td><StatusPill status={memoryStatus(entry)} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
