"""Knowledge / RAG (M9): reference material uploaded or registered by an organization.

Separate from M8 memory: memory is what runs remember; knowledge is external material that is
ingested, chunked, embedded and searched with citations. No table is shared between the two.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Float, UserDefinedType

from app.db.session import Base
from app.models.agents import JSONDocument, string_enum
from app.models.identity import Timestamps

# One fixed dimension: the size of common small embedding models (all-MiniLM-L6-v2,
# bge-small-en) and of OpenAI text-embedding-3-small with dimensions=384, so a real provider
# can replace the deterministic one without a schema change.
EMBEDDING_DIMENSION = 384


class Vector(UserDefinedType):
    """pgvector `vector(n)`. Values travel as pgvector's text form '[x1,x2,...]'.

    On SQLite (the non-vector test fallback) the declared type is accepted verbatim and the
    value is stored as text; similarity is then computed in Python after SQL filtering.
    """

    cache_ok = True

    def __init__(self, dimension: int = EMBEDDING_DIMENSION):
        self.dimension = dimension

    def get_col_spec(self, **kw) -> str:
        return f"vector({self.dimension})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            return "[" + ",".join(format(float(item), ".7g") for item in value) + "]"

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None or isinstance(value, list):
                return value
            return [float(item) for item in str(value).strip("[]").split(",") if item]

        return process

    class comparator_factory(UserDefinedType.Comparator):
        def cosine_distance(self, other):
            return self.op("<=>", return_type=Float())(other)


# Let reflection (alembic check) recognise pgvector columns instead of warning.
ischema_names["vector"] = Vector


class KnowledgeSourceType(StrEnum):
    TEXT = "text"  # documents are pasted text
    FILE = "file"  # documents are uploaded .txt / .md / .pdf / .docx files


class KnowledgeSourceStatus(StrEnum):
    DRAFT = "draft"  # no documents yet
    PROCESSING = "processing"  # at least one document is being ingested
    READY = "ready"  # at least one searchable document, none processing
    FAILED = "failed"  # documents exist but none is searchable
    ARCHIVED = "archived"  # excluded from retrieval and agents; data kept


class KnowledgeDocumentStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    CANCELLED = "cancelled"


class KnowledgeSource(Timestamps, Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_knowledge_sources_id_organization"),
        UniqueConstraint("organization_id", "name", name="uq_knowledge_sources_organization_name"),
        Index("ix_knowledge_sources_organization_status", "organization_id", "status"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1000), default="", server_default="")
    source_type: Mapped[KnowledgeSourceType] = mapped_column(
        string_enum(KnowledgeSourceType, "knowledge_source_type")
    )
    status: Mapped[KnowledgeSourceStatus] = mapped_column(
        string_enum(KnowledgeSourceStatus, "knowledge_source_status"),
        default=KnowledgeSourceStatus.DRAFT,
        server_default=KnowledgeSourceStatus.DRAFT.value,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    embedding_provider: Mapped[str] = mapped_column(String(40))
    embedding_model: Mapped[str] = mapped_column(String(80))
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    chunking_strategy: Mapped[dict[str, Any]] = mapped_column(JSONDocument)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONDocument, default=dict)
    document_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeDocument(Timestamps, Base):
    """One uploaded file or pasted text. The raw bytes live in the upload store, addressed by
    (organization, document, version); the database keeps metadata and chunks only."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["knowledge_sources.id", "knowledge_sources.organization_id"],
            name="fk_knowledge_documents_source_organization",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", name="uq_knowledge_documents_id_organization"),
        # Same name in a source = same document; a new upload replaces its content.
        UniqueConstraint("source_id", "name", name="uq_knowledge_documents_source_name"),
        Index("ix_knowledge_documents_source_status", "source_id", "status"),
        Index("ix_knowledge_documents_checksum", "source_id", "checksum"),
        CheckConstraint("size_bytes >= 0", name="ck_knowledge_documents_size"),
        CheckConstraint("version >= 1", name="ck_knowledge_documents_version"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(200))
    extension: Mapped[str] = mapped_column(String(10))
    mime_type: Mapped[str] = mapped_column(String(120))
    status: Mapped[KnowledgeDocumentStatus] = mapped_column(
        string_enum(KnowledgeDocumentStatus, "knowledge_document_status"),
        default=KnowledgeDocumentStatus.PROCESSING,
        server_default=KnowledgeDocumentStatus.PROCESSING.value,
    )
    # SHA-256 of the current content; version increments when the content is replaced.
    checksum: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Version whose chunks are currently stored (NULL: none yet).
    ingested_version: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Extraction facts only (page count, characters, parser); never the text or a path.
    extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    ingestion_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["knowledge_documents.id", "knowledge_documents.organization_id"],
            name="fk_knowledge_chunks_document_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["knowledge_sources.id", "knowledge_sources.organization_id"],
            name="fk_knowledge_chunks_source_organization",
            ondelete="CASCADE",
        ),
        # Replace-in-transaction plus this key: a retried ingestion can never duplicate chunks.
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_document_index"),
        Index("ix_knowledge_chunks_org_source", "organization_id", "source_id"),
        # PostgreSQL only: approximate nearest-neighbour and full-text indexes.
        Index(
            "ix_knowledge_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_knowledge_chunks_content_fts",
            text("to_tsvector('english', content)"),
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    char_count: Mapped[int] = mapped_column(Integer)
    token_estimate: Mapped[int] = mapped_column(Integer)
    # page, heading, document name, source name, chunk index: everything a citation needs.
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONDocument)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSION))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentKnowledgeSource(Timestamps, Base):
    """Explicit grant: this agent may search this source (with the knowledge_search tool)."""

    __tablename__ = "agent_knowledge_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_agent_knowledge_sources_agent_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["knowledge_sources.id", "knowledge_sources.organization_id"],
            name="fk_agent_knowledge_sources_source_organization",
            ondelete="CASCADE",
        ),
        UniqueConstraint("agent_id", "source_id", name="uq_agent_knowledge_sources_agent_source"),
        Index("ix_agent_knowledge_sources_org_agent", "organization_id", "agent_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
