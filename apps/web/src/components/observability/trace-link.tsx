"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef } from "react";
import { useResource } from "@/components/agents/resource";
import { useWorkspace } from "@/components/workspace-shell";
import { listTraces } from "@/lib/api/observability";
import { formatMs } from "@/lib/observability";

/** "View trace" for a run (one trace per run); refreshes with the run it belongs to. */
export function TraceLink({ runId, version }: { runId: string; version?: string }) {
  const organization = useWorkspace();
  const load = useCallback(
    () => listTraces(organization.id, { run_id: runId, origin: "all", limit: 1 }),
    [organization.id, runId],
  );
  const { data, reload } = useResource(load);
  const seen = useRef(version);
  useEffect(() => {
    // Re-query when the run's status changes: the worker has recorded new spans.
    if (seen.current !== version) {
      seen.current = version;
      reload();
    }
  }, [version, reload]);
  const trace = data?.[0];
  if (!trace) return null;
  return (
    <section className="panel trace-link">
      <h2>Observability</h2>
      <p className="mono muted-text">
        {trace.span_count} spans · {trace.attempt_count} attempt
        {trace.attempt_count === 1 ? "" : "s"} · queue wait {formatMs(trace.queue_wait_ms)}
      </p>
      <Link href={`/app/traces/${trace.id}`}>Open trace waterfall →</Link>
    </section>
  );
}
