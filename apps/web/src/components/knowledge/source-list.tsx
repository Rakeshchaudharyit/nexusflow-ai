"use client";

import Link from "next/link";
import { useCallback } from "react";
import { formatDate, usePolling, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { LoadingState, PageHeader } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import { listSources } from "@/lib/api/knowledge";
import { sourceIsBusy } from "@/lib/knowledge";
import { SearchPanel } from "./search-panel";

export function SourceList() {
  const organization = useWorkspace();
  const load = useCallback(() => listSources(organization.id), [organization.id]);
  const { data: sources, error, loading, reload } = useResource(load);
  usePolling(!!sources?.some(sourceIsBusy), reload);
  const canManage = organization.role !== "member";
  return (
    <>
      <PageHeader
        eyebrow={`KNOWLEDGE / ${organization.name}`}
        title="Knowledge"
        description="Reference documents agents can search with hybrid retrieval and cite. Ingestion runs on the background worker; agents only see sources assigned to them."
        actions={
          canManage ? (
            <Link className="primary-button" href="/app/knowledge/new">
              New Source
            </Link>
          ) : undefined
        }
      />
      {error && <p className="form-error" role="alert">{error}</p>}
      {loading && <LoadingState />}
      {sources && sources.length === 0 && (
        <p className="muted-text">
          No knowledge sources yet.{" "}
          {canManage ? "Create one, upload documents, then assign it to an agent." : ""}
        </p>
      )}
      {sources && sources.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Type</th>
                <th>Status</th>
                <th>Documents</th>
                <th>Chunks</th>
                <th>Embeddings</th>
                <th>Last ingestion</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <tr key={source.id}>
                  <td>
                    <Link href={`/app/knowledge/${source.id}`}>{source.name}</Link>
                    {source.agent_count > 0 && (
                      <span className="memory-chip"> {source.agent_count} agents</span>
                    )}
                  </td>
                  <td className="mono">{source.source_type}</td>
                  <td><StatusPill status={source.status} /></td>
                  <td className="mono">{source.document_count}</td>
                  <td className="mono">{source.chunk_count}</td>
                  <td className="mono nowrap">
                    {source.embedding_provider} · {source.embedding_dimension}d
                  </td>
                  <td className="nowrap">{formatDate(source.last_ingested_at)}</td>
                  <td className="nowrap">{formatDate(source.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sources && sources.some((source) => source.chunk_count > 0) && (
        <SearchPanel title="Search all sources" />
      )}
    </>
  );
}
