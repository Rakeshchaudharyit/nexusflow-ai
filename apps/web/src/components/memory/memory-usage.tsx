import Link from "next/link";
import type { MemoryUsage } from "@/lib/api/memory";
import { usageLine } from "@/lib/memory";

/** Count-only view of the memory a run received; the memory text is never shown here. */
export function MemoryUsagePanel({
  threadId,
  usage,
}: {
  threadId: string | null;
  usage: MemoryUsage | null;
}) {
  if (!threadId && !usage) return null;
  return (
    <section className="panel">
      <h2>Memory context used</h2>
      <p className="mono muted-text">{usageLine(usage) ?? "No memory was injected."}</p>
      {threadId && (
        <Link href={`/app/threads/${threadId}`}>View thread memory</Link>
      )}
    </section>
  );
}
