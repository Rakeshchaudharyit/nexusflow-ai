import type {
  Citation,
  KnowledgeDocument,
  KnowledgeSource,
  KnowledgeSourceStatus,
} from "./api/knowledge";

export const ACCEPTED_EXTENSIONS = [".txt", ".md", ".pdf", ".docx"] as const;
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(",");
/** Client-side hint only; the API enforces KNOWLEDGE_MAX_FILE_MB (default 10). */
export const MAX_UPLOAD_MB = 10;

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Early, friendly rejection before upload; the server repeats every check. */
export function fileProblem(file: Pick<File, "name" | "size">, maxMb = MAX_UPLOAD_MB): string | null {
  const extension = file.name.includes(".")
    ? `.${file.name.split(".").pop()?.toLowerCase()}`
    : "";
  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(extension))
    return "Unsupported file type. Upload .txt, .md, .pdf or .docx.";
  if (file.size === 0) return "The file is empty.";
  if (file.size > maxMb * 1024 * 1024) return `Files may be at most ${maxMb} MB.`;
  return null;
}

/** Poll (bounded, 2 s) only while the worker may still change something. */
export const sourceIsBusy = (source: Pick<KnowledgeSource, "status"> & { documents?: KnowledgeDocument[] }) =>
  source.status === "processing" ||
  (source.documents ?? []).some((document) => document.status === "processing");

/** One honest line about a document's ingestion, from real backend state. */
export function documentState(document: KnowledgeDocument): string {
  const job = document.ingestion;
  if (document.status === "processing") {
    if (job?.status === "retrying")
      return `Retrying (attempt ${job.attempt} of ${job.max_attempts})${
        document.error_code ? ` · ${document.error_code}` : ""
      }`;
    if (job?.cancellation_requested) return "Cancelling at the next stage";
    if (job?.status === "running") return `Extracting, chunking and embedding (attempt ${job.attempt})`;
    return document.chunk_count
      ? "Queued for re-indexing · previous version still searchable"
      : "Queued for the worker";
  }
  if (document.status === "ready")
    return `${document.chunk_count} chunks${
      document.extraction?.pages ? ` · ${document.extraction.pages} pages` : ""
    }${document.ingestion_ms !== null ? ` · ${document.ingestion_ms} ms` : ""}`;
  if (document.status === "cancelled") return "Ingestion cancelled";
  return document.error_message ?? "Ingestion failed";
}

export const assignable = (status: KnowledgeSourceStatus) =>
  status !== "archived" && status !== "failed";

/** "Security.pdf · page 4 · Identity" */
export function locator(citation: Pick<Citation, "document_name" | "page" | "section">): string {
  return [
    citation.document_name,
    citation.page ? `page ${citation.page}` : null,
    citation.section,
  ]
    .filter(Boolean)
    .join(" · ");
}

export type Segment = { text: string } | { citation: string };

/** Split answer text into prose and [K#] references for rendering as citation chips. */
export function splitCitations(text: string): Segment[] {
  const segments: Segment[] = [];
  let last = 0;
  for (const match of text.matchAll(/\[(K\d+)\]/g)) {
    if (match.index > last) segments.push({ text: text.slice(last, match.index) });
    segments.push({ citation: match[1] });
    last = match.index + match[0].length;
  }
  if (last < text.length) segments.push({ text: text.slice(last) });
  return segments;
}

export const percent = (score: number) => `${Math.round(score * 100)}%`;
