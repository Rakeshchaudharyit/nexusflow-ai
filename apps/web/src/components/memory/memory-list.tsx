"use client";

import { useCallback, useState } from "react";
import { useResource } from "@/components/agents/resource";
import { LoadingState, PageHeader } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import { listMemory, type MemoryScope, type MemoryType } from "@/lib/api/memory";
import { MemoryForm } from "./memory-form";
import { MemoryTable } from "./memory-table";

const TYPES: MemoryType[] = [
  "fact_memory",
  "thread_memory",
  "agent_memory",
  "workspace_memory",
  "summary_memory",
];
const SCOPES: MemoryScope[] = ["thread", "agent", "workspace"];

export function MemoryList() {
  const organization = useWorkspace();
  const [type, setType] = useState<MemoryType | "">("");
  const [scope, setScope] = useState<MemoryScope | "">("");
  const [active, setActive] = useState<"true" | "false" | "">("true");
  const load = useCallback(
    () =>
      listMemory(organization.id, {
        memory_type: type || undefined,
        scope: scope || undefined,
        active: active === "" ? undefined : active === "true",
      }),
    [organization.id, type, scope, active],
  );
  const { data: entries, error, loading, reload } = useResource(load);
  const manager = organization.role !== "member";
  return (
    <>
      <PageHeader
        eyebrow={`MEMORY / ${organization.name}`}
        title="Memory"
        description="Typed, scoped memory for this workspace only. Runs receive a bounded, prioritised subset: thread memory in its thread, agent memory for that agent, workspace memory only where enabled."
      />
      <div className="filter-row">
        <label>
          Type
          <select value={type} onChange={(event) => setType(event.target.value as MemoryType | "")}>
            <option value="">All types</option>
            {TYPES.map((value) => <option key={value} value={value}>{value.replace("_", " ")}</option>)}
          </select>
        </label>
        <label>
          Scope
          <select value={scope} onChange={(event) => setScope(event.target.value as MemoryScope | "")}>
            <option value="">All scopes</option>
            {SCOPES.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label>
          Status
          <select value={active} onChange={(event) => setActive(event.target.value as "true" | "false" | "")}>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
            <option value="">All</option>
          </select>
        </label>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <LoadingState />}
      {entries && <MemoryTable entries={entries} />}
      {manager ? (
        <section className="panel">
          <h2>Add workspace memory</h2>
          <p className="muted-text">
            Workspace memory reaches only agents and teams with workspace memory turned on.
            Add thread memory from a thread page.
          </p>
          <MemoryForm scope="workspace" onCreated={reload} />
        </section>
      ) : (
        <p className="muted-text">Members add memory from a thread page; workspace and agent memory are managed by owners and admins.</p>
      )}
    </>
  );
}
