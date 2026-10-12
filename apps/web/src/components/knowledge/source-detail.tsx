"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState, type FormEvent, type SyntheticEvent } from "react";
import { describeError, formatDate, usePolling, useResource } from "@/components/agents/resource";
import { StatusPill } from "@/components/agents/status-pill";
import { LoadingState } from "@/components/ui/design-system";
import { useWorkspace } from "@/components/workspace-shell";
import {
  addTextDocument,
  cancelDocument,
  deleteDocument,
  deleteSource,
  getDocument,
  getSource,
  reindexSource,
  updateSource,
  uploadDocument,
  type KnowledgeDocument,
  type KnowledgeDocumentDetail,
} from "@/lib/api/knowledge";
import {
  ACCEPT_ATTRIBUTE,
  documentState,
  fileProblem,
  formatBytes,
  sourceIsBusy,
} from "@/lib/knowledge";
import { SearchPanel } from "./search-panel";

function DocumentChunks({ document }: { document: KnowledgeDocument }) {
  const organization = useWorkspace();
  const [detail, setDetail] = useState<KnowledgeDocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function toggle(event: SyntheticEvent<HTMLDetailsElement>) {
    if (!event.currentTarget.open || detail) return;
    try {
      setDetail(await getDocument(organization.id, document.id));
    } catch (failure) {
      setError(describeError(failure));
    }
  }
  if (!document.chunk_count) return null;
  return (
    <details className="technical-log" onToggle={toggle}>
      <summary>Chunks · {document.chunk_count}</summary>
      {error && <p className="form-error">{error}</p>}
      {!detail && !error && <p className="muted-text">Loading chunks…</p>}
      {detail && (
        <ol className="chunk-list">
          {detail.chunks.map((chunk) => (
            <li key={chunk.id}>
              <span className="mono muted-text">
                #{chunk.chunk_index}
                {chunk.page ? ` · page ${chunk.page}` : ""}
                {chunk.section ? ` · ${chunk.section}` : ""} · {chunk.char_count} chars · ~
                {chunk.token_estimate} tokens
              </span>
              <p>{chunk.preview}{chunk.char_count > chunk.preview.length ? "…" : ""}</p>
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}

export function SourceDetail({ sourceId }: { sourceId: string }) {
  const organization = useWorkspace();
  const router = useRouter();
  const load = useCallback(() => getSource(organization.id, sourceId), [organization.id, sourceId]);
  const { data: source, error, notFound, loading, reload } = useResource(load);
  // Bounded 2 s polling while the worker is ingesting; stops when every document settles.
  usePolling(!!source && sourceIsBusy(source), reload);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const canManage = organization.role !== "member";

  async function act(label: string, action: () => Promise<unknown>, done?: string) {
    if (busy) return;
    setBusy(label);
    setFailure(null);
    setNotice(null);
    try {
      await action();
      if (done) setNotice(done);
      reload();
    } catch (problem) {
      setFailure(describeError(problem));
    } finally {
      setBusy(null);
    }
  }

  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file) return;
    const problem = fileProblem(file);
    if (problem) {
      setFailure(problem);
      return;
    }
    const form = event.currentTarget;
    void act(
      "upload",
      async () => {
        const result = await uploadDocument(organization.id, sourceId, file);
        form.reset();
        return result;
      },
      `${file.name} uploaded and queued. The status below updates as the worker extracts, chunks and embeds it.`,
    );
  }

  function addText(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    void act(
      "upload",
      async () => {
        await addTextDocument(organization.id, sourceId, {
          name: String(data.get("name") ?? "").trim(),
          content: String(data.get("content") ?? "").trim(),
        });
        form.reset();
      },
      "Text added and queued. The status below updates as the worker chunks and embeds it.",
    );
  }

  if (loading) return <LoadingState />;
  if (notFound || !source)
    return (
      <section className="panel narrow">
        <h1>{notFound ? "Knowledge source not found" : "Could not load this source"}</h1>
        <p className="muted-text">
          {notFound ? `This source does not exist in ${organization.name}.` : error}
        </p>
        <Link href="/app/knowledge">Back to knowledge</Link>
      </section>
    );
  const archived = source.status === "archived";
  const processing = sourceIsBusy(source);
  return (
    <>
      <div className="page-header">
        <div>
          <p className="eyebrow">KNOWLEDGE / {organization.name}</p>
          <h1>{source.name}</h1>
          {source.description && <p className="page-description">{source.description}</p>}
        </div>
        <Link href="/app/knowledge">Back to knowledge</Link>
      </div>
      <section className="panel">
        <dl className="details">
          <dt>Status</dt>
          <dd><StatusPill status={source.status} /></dd>
          <dt>Type</dt>
          <dd className="mono">{source.source_type === "file" ? "files" : "pasted text"}</dd>
          <dt>Embeddings</dt>
          <dd className="mono">
            {source.embedding_provider} · {source.embedding_model} · {source.embedding_dimension}{" "}
            dimensions · pgvector HNSW (cosine)
          </dd>
          <dt>Chunking</dt>
          <dd className="mono">
            {source.chunking_strategy.strategy ?? "structure-aware"} ·{" "}
            {source.chunking_strategy.chunk_size} chars · {source.chunking_strategy.chunk_overlap}{" "}
            overlap
          </dd>
          <dt>Contents</dt>
          <dd className="mono">
            {source.document_count} documents · {source.chunk_count}{" "}
            {archived ? "chunks (excluded while archived)" : "searchable chunks"}
          </dd>
          <dt>Last ingestion</dt>
          <dd>{formatDate(source.last_ingested_at)}</dd>
          <dt>Agents with access</dt>
          <dd>
            {source.agents.length
              ? source.agents.map((agent, index) => (
                  <span key={agent.agent_id}>
                    {index > 0 && ", "}
                    <Link href={`/app/agents/${agent.agent_id}`}>{agent.agent_name}</Link>
                    {!agent.is_enabled && " (disabled)"}
                    {agent.is_enabled && !agent.has_search_tool && " (needs knowledge_search tool)"}
                  </span>
                ))
              : "None. Assign this source from an agent's page."}
          </dd>
        </dl>
        {canManage && (
          <div className="button-row">
            <button
              disabled={!!busy || archived || processing || !source.document_count}
              onClick={() =>
                void act(
                  "reindex",
                  () => reindexSource(organization.id, sourceId),
                  "Re-index queued. Chunks are replaced document by document; nothing is duplicated.",
                )
              }
            >
              {busy === "reindex" ? "Queuing…" : "Reindex"}
            </button>
            <button
              disabled={!!busy || processing}
              onClick={() =>
                void act(
                  "archive",
                  () => updateSource(organization.id, sourceId, { archived: !archived }),
                  archived
                    ? "Source restored. Assigned agents can search it again."
                    : "Source archived. It is excluded from retrieval and agents immediately.",
                )
              }
            >
              {archived ? "Unarchive" : "Archive"}
            </button>
            <button
              className="danger-button"
              disabled={!!busy || processing}
              onClick={() => {
                if (
                  !window.confirm(
                    `Delete ${source.name}? Its documents, chunks, vectors and agent assignments are removed permanently.`,
                  )
                )
                  return;
                void act("delete", async () => {
                  await deleteSource(organization.id, sourceId);
                  router.push("/app/knowledge");
                });
              }}
            >
              Delete
            </button>
          </div>
        )}
        {notice && <p className="muted-text" role="status">{notice}</p>}
        {failure && <p className="form-error" role="alert">{failure}</p>}
      </section>
      {canManage && !archived && (
        <section className="panel">
          <h2>{source.source_type === "file" ? "Upload document" : "Add text"}</h2>
          {source.source_type === "file" ? (
            <form onSubmit={upload} className="filter-row">
              <label className="grow">
                File
                <input ref={fileInput} type="file" name="file" accept={ACCEPT_ATTRIBUTE} required />
              </label>
              <button className="primary-button" disabled={!!busy}>
                {busy === "upload" ? "Uploading…" : "Upload Document"}
              </button>
            </form>
          ) : (
            <form onSubmit={addText}>
              <label>
                Name
                <input name="name" required maxLength={200} placeholder="Renewal notes" />
              </label>
              <label>
                Text
                <textarea name="content" required rows={6} maxLength={500000} />
              </label>
              <button className="primary-button" disabled={!!busy}>
                {busy === "upload" ? "Adding…" : "Add Text"}
              </button>
            </form>
          )}
          <p className="field-hint">
            .txt, .md, .pdf (text only, no OCR) and .docx up to 10 MB. Uploading the same
            content twice is rejected; a new file with an existing name replaces that document.
          </p>
        </section>
      )}
      <section className="panel">
        <h2>Documents</h2>
        {source.documents.length === 0 ? (
          <p className="muted-text">No documents yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Type</th>
                  <th>Size</th>
                  <th>Status</th>
                  <th>Ingestion</th>
                  {canManage && <th />}
                </tr>
              </thead>
              <tbody>
                {source.documents.map((document) => (
                  <tr key={document.id}>
                    <td>
                      {document.name}
                      {document.version > 1 && <span className="memory-chip"> v{document.version}</span>}
                      <DocumentChunks document={document} />
                    </td>
                    <td className="mono">{document.extension.slice(1)}</td>
                    <td className="mono nowrap">{formatBytes(document.size_bytes)}</td>
                    <td><StatusPill status={document.status} /></td>
                    <td>
                      <span className={document.status === "failed" ? "form-error" : "muted-text"}>
                        {documentState(document)}
                      </span>
                      {document.error_code && document.status === "failed" && (
                        <span className="mono muted-text"> ({document.error_code})</span>
                      )}
                    </td>
                    {canManage && (
                      <td className="nowrap">
                        {document.status === "processing" ? (
                          <button
                            disabled={!!busy || !!document.ingestion?.cancellation_requested}
                            onClick={() =>
                              void act("cancel", () => cancelDocument(organization.id, document.id))
                            }
                          >
                            Cancel
                          </button>
                        ) : (
                          <button
                            disabled={!!busy}
                            onClick={() => {
                              if (window.confirm(`Delete ${document.name} and its chunks?`))
                                void act("remove", () => deleteDocument(organization.id, document.id));
                            }}
                          >
                            Delete
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {!archived && source.chunk_count > 0 && <SearchPanel sourceIds={[source.id]} />}
      {archived && (
        <p className="muted-text">
          Archived sources are excluded from search and from every agent until restored.
        </p>
      )}
    </>
  );
}
