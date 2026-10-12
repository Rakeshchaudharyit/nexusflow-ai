"""Hybrid retrieval: semantic (pgvector cosine) + lexical (keywords), tenant-filtered in SQL.

Every candidate query carries `organization_id = :org AND source_id IN (:allowed)` plus the
source/document state filters *inside* the SQL statement, so the nearest-neighbour search
never sees another tenant's or an unassigned source's vectors; nothing is filtered afterwards
in Python.

Scoring (all in [0, 1], deterministic):

    semantic_score = max(0, cosine_similarity(query_vector, chunk_vector))
    lexical_score  = share of the query's distinct keywords present in the chunk
    hybrid_score   = KNOWLEDGE_SEMANTIC_WEIGHT * semantic + KNOWLEDGE_LEXICAL_WEIGHT * lexical

Candidates are the union of the top semantic matches and (PostgreSQL) the top full-text
matches, so a keyword-only hit can still win. Results below KNOWLEDGE_MIN_SCORE are dropped;
ties break on (document name, chunk index). Diversity: no duplicate content, no directly
adjacent (overlapping) chunk of an already selected one, at most 3 chunks per document; and
the total excerpt text stays within KNOWLEDGE_MAX_CONTEXT_CHARS.
"""

import math
import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import and_, func, literal_column, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.knowledge.embeddings import EmbeddingProvider
from app.knowledge.lifecycle import SEARCHABLE
from app.knowledge.text import STOPWORDS, WORD, keywords, terms
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeSource,
    KnowledgeSourceStatus,
)

CANDIDATES_PER_K = 4
MAX_PER_DOCUMENT = 3
EXCERPT_CHARS = 400
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True)
class Hit:
    citation_id: str
    chunk_id: UUID
    source_id: UUID
    source_name: str
    document_id: UUID
    document_name: str
    chunk_index: int
    page: int | None
    heading: str | None
    excerpt: str
    score: float
    semantic_score: float
    lexical_score: float

    def citation(self) -> dict:
        """Safe, structured citation: names and ids only, never storage paths."""
        return {
            "citation_id": self.citation_id,
            "source_id": str(self.source_id),
            "source_name": self.source_name,
            "document_id": str(self.document_id),
            "document_name": self.document_name,
            "chunk_id": str(self.chunk_id),
            "chunk_index": self.chunk_index,
            "page": self.page,
            "section": self.heading,
            "excerpt": self.excerpt,
            "score": self.score,
        }


@dataclass(frozen=True)
class Retrieval:
    query: str
    hits: list[Hit]
    sources_searched: list[dict] = field(default_factory=list)
    candidates: int = 0
    truncated: bool = False

    @property
    def insufficient(self) -> bool:
        return not self.hits


def excerpt(content: str, query_terms: set[str], limit: int = EXCERPT_CHARS) -> str:
    """The most query-relevant sentence(s) of a chunk, bounded; falls back to its start."""
    sentences = [part.strip() for part in SENTENCE.split(content) if part.strip()]
    if not sentences:
        return content[:limit]
    best = max(
        range(len(sentences)),
        key=lambda i: (len(query_terms & set(terms(sentences[i]))), -i),
    )
    picked = sentences[best]
    for following in sentences[best + 1 :]:
        if len(picked) + 1 + len(following) > limit:
            break
        picked = f"{picked} {following}"
    return picked if len(picked) <= limit else picked[: limit - 1].rstrip() + "…"


def lexical_score(query_terms: list[str], content: str) -> float:
    if not query_terms:
        return 0.0
    present = set(terms(content))
    return sum(1 for term in query_terms if term in present) / len(query_terms)


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    norm = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return dot / norm if norm else 0.0


def usable_sources(db: Session, organization_id: UUID, source_ids: list[UUID]) -> list:
    """The allowed sources that may be searched now: same tenant and not archived."""
    if not source_ids:
        return []
    return list(
        db.execute(
            select(KnowledgeSource.id, KnowledgeSource.name)
            .where(
                KnowledgeSource.organization_id == organization_id,
                KnowledgeSource.id.in_(source_ids),
                KnowledgeSource.status != KnowledgeSourceStatus.ARCHIVED,
            )
            .order_by(KnowledgeSource.name)
        ).all()
    )


def _scope(organization_id: UUID, source_ids: list[UUID]):
    """Tenant + permission + lifecycle predicate applied inside every candidate query."""
    return and_(
        KnowledgeChunk.organization_id == organization_id,
        KnowledgeChunk.source_id.in_(source_ids),
        KnowledgeSource.status != KnowledgeSourceStatus.ARCHIVED,
        KnowledgeDocument.status.in_(SEARCHABLE),
    )


def _base(columns):
    return (
        select(*columns)
        .join(
            KnowledgeSource,
            and_(
                KnowledgeSource.id == KnowledgeChunk.source_id,
                KnowledgeSource.organization_id == KnowledgeChunk.organization_id,
            ),
        )
        .join(
            KnowledgeDocument,
            and_(
                KnowledgeDocument.id == KnowledgeChunk.document_id,
                KnowledgeDocument.organization_id == KnowledgeChunk.organization_id,
            ),
        )
    )


def _candidates(db, organization_id, source_ids, vector, words, limit):
    """Return {chunk_id: semantic_score}."""
    scope = _scope(organization_id, source_ids)
    if db.get_bind().dialect.name == "postgresql":
        # Let HNSW keep scanning until enough rows pass the tenant filter (pgvector >= 0.8).
        db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        distance = KnowledgeChunk.embedding.cosine_distance(vector)
        semantic = dict(
            db.execute(
                _base([KnowledgeChunk.id, (1 - distance).label("similarity")])
                .where(scope)
                .order_by(distance, KnowledgeChunk.id)
                .limit(limit)
            ).all()
        )
        if words:
            # Keyword recall through the GIN full-text index: OR of the query's words, which
            # are [a-z0-9]+ only, so the tsquery text cannot carry operators.
            tsquery = func.to_tsquery("english", " | ".join(words))
            document = func.to_tsvector(literal_column("'english'"), KnowledgeChunk.content)
            lexical_ids = db.scalars(
                _base([KnowledgeChunk.id])
                .where(scope, document.op("@@")(tsquery))
                .order_by(func.ts_rank_cd(document, tsquery).desc(), KnowledgeChunk.id)
                .limit(limit)
            ).all()
            missing = [chunk_id for chunk_id in lexical_ids if chunk_id not in semantic]
            if missing:
                semantic |= dict(
                    db.execute(
                        _base([KnowledgeChunk.id, (1 - distance).label("similarity")]).where(
                            scope, KnowledgeChunk.id.in_(missing)
                        )
                    ).all()
                )
        return {chunk_id: float(score or 0.0) for chunk_id, score in semantic.items()}
    # SQLite test fallback: same SQL scope filter first, similarity computed in Python.
    rows = db.execute(_base([KnowledgeChunk.id, KnowledgeChunk.embedding]).where(scope)).all()
    return {chunk_id: cosine(vector, embedding) for chunk_id, embedding in rows}


def search(
    db: Session,
    settings: Settings,
    embedder: EmbeddingProvider,
    *,
    organization_id: UUID,
    query: str,
    source_ids: list[UUID],
    top_k: int | None = None,
) -> Retrieval:
    top_k = min(top_k or settings.knowledge_top_k, 20)
    sources = usable_sources(db, organization_id, source_ids)
    searched = [{"source_id": str(row.id), "source_name": row.name} for row in sources]
    query_terms = [term for term in keywords(query) if re.fullmatch(r"[a-z0-9]+", term)]
    if not sources or not query_terms:
        return Retrieval(query, [], searched)
    vector = embedder.embed([query])[0]
    ids = [row.id for row in sources]
    words = list(dict.fromkeys(w for w in WORD.findall(query.casefold()) if w not in STOPWORDS))
    candidates = _candidates(db, organization_id, ids, vector, words, top_k * CANDIDATES_PER_K)
    if not candidates:
        return Retrieval(query, [], searched)
    rows = db.execute(
        _base([KnowledgeChunk, KnowledgeDocument.name, KnowledgeSource.name]).where(
            _scope(organization_id, ids), KnowledgeChunk.id.in_(list(candidates))
        )
    ).all()
    scored = []
    for chunk, document_name, source_name in rows:
        semantic = max(0.0, min(1.0, candidates[chunk.id]))
        lexical = lexical_score(query_terms, chunk.content)
        score = (
            settings.knowledge_semantic_weight * semantic
            + settings.knowledge_lexical_weight * lexical
        )
        if score >= settings.knowledge_min_score:
            scored.append((round(score, 4), semantic, lexical, chunk, document_name, source_name))
    scored.sort(key=lambda item: (-item[0], item[4], item[3].chunk_index, str(item[3].id)))
    hits: list[Hit] = []
    seen_hashes: set[str] = set()
    per_document: dict[UUID, list[int]] = {}
    budget, truncated = settings.knowledge_max_context_chars, False
    term_set = set(query_terms)
    for score, semantic, lexical, chunk, document_name, source_name in scored:
        if len(hits) == top_k:
            break
        taken = per_document.get(chunk.document_id, [])
        if (
            chunk.content_hash in seen_hashes
            or len(taken) >= MAX_PER_DOCUMENT
            or any(abs(index - chunk.chunk_index) == 1 for index in taken)
        ):
            continue
        snippet = excerpt(chunk.content, term_set)
        if len(snippet) > budget:
            truncated = True
            break
        budget -= len(snippet)
        seen_hashes.add(chunk.content_hash)
        per_document.setdefault(chunk.document_id, []).append(chunk.chunk_index)
        metadata = chunk.metadata_json or {}
        hits.append(
            Hit(
                citation_id=f"K{len(hits) + 1}",
                chunk_id=chunk.id,
                source_id=chunk.source_id,
                source_name=source_name,
                document_id=chunk.document_id,
                document_name=document_name,
                chunk_index=chunk.chunk_index,
                page=metadata.get("page"),
                heading=metadata.get("heading"),
                excerpt=snippet,
                score=score,
                semantic_score=round(semantic, 4),
                lexical_score=round(lexical, 4),
            )
        )
    return Retrieval(query, hits, searched, len(candidates), truncated)
