import Link from "next/link";
import type { Citation, KnowledgeRetrieval } from "@/lib/api/knowledge";
import { locator, percent, splitCitations } from "@/lib/knowledge";

/** Answer text with [K#] references rendered as chips that jump to their citation. */
export function CitedText({ text, citations }: { text: string; citations: Citation[] }) {
  const known = new Set(citations.map((citation) => citation.citation_id));
  return (
    <>
      {splitCitations(text).map((segment, index) =>
        "citation" in segment ? (
          known.has(segment.citation) ? (
            <a key={index} className="citation-chip" href={`#citation-${segment.citation}`}>
              {segment.citation}
            </a>
          ) : (
            <span key={index} className="mono">[{segment.citation}]</span>
          )
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </>
  );
}

/** Structured citations: the source, document, page/section and chunk behind each [K#]. */
export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <ol className="citation-list">
      {citations.map((citation) => (
        <li key={citation.citation_id} id={`citation-${citation.citation_id}`}>
          <span className="citation-chip">{citation.citation_id}</span>
          <div>
            <strong>{locator(citation)}</strong>
            <p className="mono muted-text">
              <Link href={`/app/knowledge/${citation.source_id}`}>{citation.source_name}</Link>
              {" · chunk "}
              {citation.chunk_index}
              {" · score "}
              {percent(citation.score)}
            </p>
            <blockquote>{citation.excerpt}</blockquote>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Run detail: what knowledge_search retrieved (never vectors or storage paths). */
export function KnowledgeRetrievalPanel({
  retrieval,
  citations,
}: {
  retrieval: KnowledgeRetrieval | null | undefined;
  citations: Citation[];
}) {
  if (!retrieval) return null;
  const used = new Set(citations.map((citation) => citation.chunk_id));
  return (
    <section className="panel">
      <h2>Knowledge retrieval</h2>
      <dl className="details">
        <dt>Query</dt>
        <dd className="preformatted">{retrieval.query}</dd>
        <dt>Sources searched</dt>
        <dd>
          {retrieval.sources_searched.length
            ? retrieval.sources_searched.map((source, index) => (
                <span key={source.source_id}>
                  {index > 0 && ", "}
                  <Link href={`/app/knowledge/${source.source_id}`}>{source.source_name}</Link>
                </span>
              ))
            : "None: every source assigned to this agent is archived"}
        </dd>
        <dt>Chunks</dt>
        <dd className="mono">
          {retrieval.results.length} retrieved · {citations.length} cited ·{" "}
          {retrieval.candidates ?? 0} candidates
        </dd>
      </dl>
      {retrieval.insufficient && (
        <p className="muted-text">
          {retrieval.sources_searched.length
            ? "No passage passed the relevance threshold"
            : "Nothing was searchable"}
          , so the agent answered that the connected knowledge sources do not contain enough
          information.
        </p>
      )}
      {retrieval.results.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Document</th>
                <th>Hybrid</th>
                <th>Semantic</th>
                <th>Keyword</th>
                <th>Used</th>
              </tr>
            </thead>
            <tbody>
              {retrieval.results.map((hit) => (
                <tr key={hit.chunk_id}>
                  <td className="mono">{hit.citation_id}</td>
                  <td>{locator(hit)}</td>
                  <td className="mono">{percent(hit.score)}</td>
                  <td className="mono">{percent(hit.semantic_score)}</td>
                  <td className="mono">{percent(hit.lexical_score)}</td>
                  <td>{used.has(hit.chunk_id) ? "cited" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {citations.length > 0 && (
        <>
          <h3>Citations</h3>
          <CitationList citations={citations} />
        </>
      )}
    </section>
  );
}
