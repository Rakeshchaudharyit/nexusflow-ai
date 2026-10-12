"use client";

import { useState, type FormEvent } from "react";
import { describeError } from "@/components/agents/resource";
import { useWorkspace } from "@/components/workspace-shell";
import { searchKnowledge, type KnowledgeSearchResult } from "@/lib/api/knowledge";
import { locator, percent } from "@/lib/knowledge";

/** Test the knowledge base: hybrid retrieval with scores and citation ids, as agents see it. */
export function SearchPanel({ sourceIds, title = "Test retrieval" }: { sourceIds?: string[]; title?: string }) {
  const organization = useWorkspace();
  const [result, setResult] = useState<KnowledgeSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const query = String(new FormData(event.currentTarget).get("query") ?? "").trim();
    if (!query) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await searchKnowledge(organization.id, { query, source_ids: sourceIds }));
    } catch (failure) {
      setError(describeError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel knowledge-search">
      <h2>{title}</h2>
      <form onSubmit={submit} className="filter-row">
        <label className="grow">
          Query
          <input
            name="query"
            required
            maxLength={500}
            placeholder="Ask the knowledge base…"
            aria-label="Ask the knowledge base"
          />
        </label>
        <button className="primary-button" disabled={busy}>
          {busy ? "Searching…" : "Search"}
        </button>
      </form>
      {error && <p className="form-error" role="alert">{error}</p>}
      {result && (
        <>
          <p className="mono muted-text">
            hybrid = {result.ranking.semantic_weight} × semantic + {result.ranking.lexical_weight} ×
            keyword · threshold {result.ranking.min_score} · top {result.ranking.top_k} ·{" "}
            {result.candidates} candidates · {result.sources_searched.length} sources searched
            {result.truncated ? " · context budget reached" : ""}
          </p>
          {result.insufficient ? (
            <p className="muted-text" role="status">
              No passage is relevant enough. An agent would answer that the connected knowledge
              sources do not contain enough information.
            </p>
          ) : (
            <ol className="citation-list">
              {result.results.map((hit) => (
                <li key={hit.chunk_id}>
                  <span className="citation-chip">{hit.citation_id}</span>
                  <div>
                    <strong>{locator(hit)}</strong>
                    <p className="mono muted-text">
                      {hit.source_name} · chunk {hit.chunk_index} · hybrid {percent(hit.score)} ·
                      semantic {percent(hit.semantic_score)} · keyword {percent(hit.lexical_score)}
                    </p>
                    <div className="score-bar" aria-hidden="true">
                      <span style={{ width: percent(hit.score) }} />
                    </div>
                    <blockquote>{hit.excerpt}</blockquote>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </>
      )}
    </section>
  );
}
