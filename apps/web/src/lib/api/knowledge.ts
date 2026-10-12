"use client";

import { authenticated, scoped } from "./auth";
import type { JobStatus } from "./jobs";

export type KnowledgeSourceType = "text" | "file";
export type KnowledgeSourceStatus = "draft" | "processing" | "ready" | "failed" | "archived";
export type KnowledgeDocumentStatus = "processing" | "ready" | "failed" | "cancelled";

/** Mirrors the API's KnowledgeSourceResponse. */
export type KnowledgeSource = {
  id: string;
  organization_id: string;
  name: string;
  description: string;
  source_type: KnowledgeSourceType;
  status: KnowledgeSourceStatus;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimension: number;
  chunking_strategy: { strategy?: string; chunk_size?: number; chunk_overlap?: number };
  document_count: number;
  chunk_count: number;
  last_ingested_at: string | null;
  archived_at: string | null;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
  agent_count: number;
};
/** The document's latest background ingestion job (M7). */
export type IngestionInfo = {
  job_id: string;
  status: JobStatus;
  attempt: number;
  max_attempts: number;
  cancellation_requested: boolean;
  error_code: string | null;
  next_retry_at: string | null;
};
export type KnowledgeDocument = {
  id: string;
  organization_id: string;
  source_id: string;
  name: string;
  extension: string;
  mime_type: string;
  status: KnowledgeDocumentStatus;
  checksum: string;
  size_bytes: number;
  version: number;
  ingested_version: number | null;
  chunk_count: number;
  extraction: {
    parser?: string;
    pages?: number | null;
    characters?: number;
    chunks?: number;
  } | null;
  ingestion_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  ingested_at: string | null;
  ingestion: IngestionInfo | null;
};
export type KnowledgeSourceDetail = KnowledgeSource & {
  documents: KnowledgeDocument[];
  agents: {
    agent_id: string;
    agent_name: string;
    is_enabled: boolean;
    has_search_tool: boolean;
  }[];
};
export type ChunkPreview = {
  id: string;
  chunk_index: number;
  page: number | null;
  section: string | null;
  char_count: number;
  token_estimate: number;
  preview: string;
};
export type KnowledgeDocumentDetail = KnowledgeDocument & {
  source_name: string;
  source_status: KnowledgeSourceStatus;
  chunks: ChunkPreview[];
};
/** A structured citation: safe names and ids only, never storage paths or vectors. */
export type Citation = {
  citation_id: string;
  source_id: string;
  source_name: string;
  document_id: string;
  document_name: string;
  chunk_id: string;
  chunk_index: number;
  page: number | null;
  section: string | null;
  excerpt: string;
  score: number;
};
export type KnowledgeHit = Citation & { semantic_score: number; lexical_score: number };
export type SearchedSource = { source_id: string; source_name: string };
export type KnowledgeSearchResult = {
  query: string;
  results: KnowledgeHit[];
  sources_searched: SearchedSource[];
  candidates: number;
  truncated: boolean;
  insufficient: boolean;
  ranking: { semantic_weight: number; lexical_weight: number; min_score: number; top_k: number };
};
/** What a run's knowledge_search call retrieved (run detail). */
export type KnowledgeRetrieval = {
  query: string;
  sources_searched: SearchedSource[];
  results: KnowledgeHit[];
  candidates: number;
  insufficient: boolean;
};
export type AgentKnowledge = {
  id: string;
  agent_id: string;
  source_id: string;
  source_name: string;
  source_status: KnowledgeSourceStatus;
  document_count: number;
  chunk_count: number;
  is_enabled: boolean;
  created_at: string;
};

const id = (value: string) => encodeURIComponent(value);
const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
});

export const listSources = (organizationId: string) =>
  authenticated<KnowledgeSource[]>("/knowledge-sources", scoped(organizationId));
export const createSource = (
  organizationId: string,
  input: { name: string; description: string; source_type: KnowledgeSourceType },
) =>
  authenticated<KnowledgeSource>(
    "/knowledge-sources",
    scoped(organizationId, json("POST", input)),
  );
export const getSource = (organizationId: string, sourceId: string) =>
  authenticated<KnowledgeSourceDetail>(`/knowledge-sources/${id(sourceId)}`, scoped(organizationId));
export const updateSource = (
  organizationId: string,
  sourceId: string,
  changes: { name?: string; description?: string; archived?: boolean },
) =>
  authenticated<KnowledgeSource>(
    `/knowledge-sources/${id(sourceId)}`,
    scoped(organizationId, json("PATCH", changes)),
  );
export const deleteSource = (organizationId: string, sourceId: string) =>
  authenticated<void>(
    `/knowledge-sources/${id(sourceId)}`,
    scoped(organizationId, { method: "DELETE" }),
  );
export const reindexSource = (organizationId: string, sourceId: string) =>
  authenticated<{ source: KnowledgeSource; queued: number; skipped: number }>(
    `/knowledge-sources/${id(sourceId)}/reindex`,
    scoped(organizationId, { method: "POST" }),
  );
type UploadResult = { document: KnowledgeDocument; outcome: "created" | "replaced" };
/** Multipart upload; the browser sets the boundary, so no JSON content type is added. */
export const uploadDocument = (organizationId: string, sourceId: string, file: File) => {
  const body = new FormData();
  body.append("file", file, file.name);
  return authenticated<UploadResult>(`/knowledge-sources/${id(sourceId)}/documents`, {
    method: "POST",
    body,
    headers: { "X-Organization-ID": organizationId },
  });
};
export const addTextDocument = (
  organizationId: string,
  sourceId: string,
  input: { name: string; content: string },
) =>
  authenticated<UploadResult>(
    `/knowledge-sources/${id(sourceId)}/documents`,
    scoped(organizationId, json("POST", input)),
  );
export const getDocument = (organizationId: string, documentId: string) =>
  authenticated<KnowledgeDocumentDetail>(
    `/knowledge-documents/${id(documentId)}`,
    scoped(organizationId),
  );
export const cancelDocument = (organizationId: string, documentId: string) =>
  authenticated<{ document: KnowledgeDocument; outcome: string }>(
    `/knowledge-documents/${id(documentId)}/cancel`,
    scoped(organizationId, { method: "POST" }),
  );
export const deleteDocument = (organizationId: string, documentId: string) =>
  authenticated<void>(
    `/knowledge-documents/${id(documentId)}`,
    scoped(organizationId, { method: "DELETE" }),
  );
export const searchKnowledge = (
  organizationId: string,
  input: { query: string; source_ids?: string[]; top_k?: number },
) =>
  authenticated<KnowledgeSearchResult>(
    "/knowledge/search",
    scoped(organizationId, json("POST", input)),
  );
export const listAgentKnowledge = (organizationId: string, agentId: string) =>
  authenticated<AgentKnowledge[]>(`/agents/${id(agentId)}/knowledge`, scoped(organizationId));
export const assignAgentKnowledge = (organizationId: string, agentId: string, sourceId: string) =>
  authenticated<AgentKnowledge>(
    `/agents/${id(agentId)}/knowledge`,
    scoped(organizationId, json("POST", { source_id: sourceId })),
  );
export const updateAgentKnowledge = (
  organizationId: string,
  agentId: string,
  sourceId: string,
  isEnabled: boolean,
) =>
  authenticated<AgentKnowledge>(
    `/agents/${id(agentId)}/knowledge/${id(sourceId)}`,
    scoped(organizationId, json("PATCH", { is_enabled: isEnabled })),
  );
export const removeAgentKnowledge = (organizationId: string, agentId: string, sourceId: string) =>
  authenticated<void>(
    `/agents/${id(agentId)}/knowledge/${id(sourceId)}`,
    scoped(organizationId, { method: "DELETE" }),
  );
