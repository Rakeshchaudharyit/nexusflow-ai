"use client";

import { useCallback } from "react";
import { useResource } from "@/components/agents/resource";
import { useWorkspace } from "@/components/workspace-shell";
import { listThreads } from "@/lib/api/memory";

/** Optional thread for a run (form field "thread_id"). Without one, runs behave as before. */
export function ThreadSelect() {
  const organization = useWorkspace();
  const load = useCallback(
    () => listThreads(organization.id, "active"),
    [organization.id],
  );
  const { data: threads } = useResource(load);
  return (
    <label>
      Thread (memory)
      <select name="thread_id" defaultValue="">
        <option value="">No thread: no memory</option>
        {(threads ?? []).map((thread) => (
          <option key={thread.id} value={thread.id}>
            {thread.title}
          </option>
        ))}
      </select>
    </label>
  );
}

export const threadField = (form: FormData) =>
  String(form.get("thread_id") ?? "") || undefined;
