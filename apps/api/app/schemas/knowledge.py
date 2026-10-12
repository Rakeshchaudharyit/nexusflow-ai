from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.jobs import JobStatus
from app.models.knowledge import (
    KnowledgeDocumentStatus,
    KnowledgeSourceStatus,
    KnowledgeSourceType,
)


class KnowledgeSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    source_type: KnowledgeSourceType = KnowledgeSourceType.FILE
    # Only the configured provider is accepted; it is recorded on the source.
    embedding_provider: Literal["deterministic_local", "openai"] | None = None


class KnowledgeSourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    archived: bool | None = None

    @model_validator(mode="after")
    def at_least_one(self):
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise ValueError("Provide name, description and/or archived")
        return self


class IngestionInfo(BaseModel):
    """The document's latest M7 ingestion job."""

    job_id: UUID
    status: JobStatus
    attempt: int
    max_attempts: int
    cancellation_requested: bool
    error_code: str | None
    next_retry_at: datetime | None


class KnowledgeSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    name: str
    description: str
    source_type: KnowledgeSourceType
    status: KnowledgeSourceStatus
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    chunking_strategy: dict[str, Any]
    document_count: int
    chunk_count: int
    last_ingested_at: datetime | None
    archived_at: datetime | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    agent_count: int = 0


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    source_id: UUID
    name: str
    extension: str
    mime_type: str
    status: KnowledgeDocumentStatus
    checksum: str
    size_bytes: int
    version: int
    ingested_version: int | None
    chunk_count: int
    extraction: dict[str, Any] | None
    ingestion_ms: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    ingested_at: datetime | None
    ingestion: IngestionInfo | None = None


class SourceAgent(BaseModel):
    agent_id: UUID
    agent_name: str
    is_enabled: bool
    has_search_tool: bool


class KnowledgeSourceDetail(KnowledgeSourceResponse):
    documents: list[KnowledgeDocumentResponse]
    agents: list[SourceAgent]


class ChunkPreview(BaseModel):
    id: UUID
    chunk_index: int
    page: int | None
    section: str | None
    char_count: int
    token_estimate: int
    preview: str


class KnowledgeDocumentDetail(KnowledgeDocumentResponse):
    source_name: str
    source_status: KnowledgeSourceStatus
    chunks: list[ChunkPreview]


class TextDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=500_000)


class DocumentUploadResult(BaseModel):
    document: KnowledgeDocumentResponse
    # created: new document; replaced: same name, new content (version + 1)
    outcome: Literal["created", "replaced"]


class ReindexResult(BaseModel):
    source: KnowledgeSourceResponse
    queued: int
    skipped: int


class DocumentCancelResult(BaseModel):
    document: KnowledgeDocumentResponse
    outcome: Literal["cancelled", "cancellation_requested"]


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500)
    source_ids: list[UUID] | None = Field(default=None, max_length=50)
    top_k: int | None = Field(default=None, ge=1, le=20)


class KnowledgeHit(BaseModel):
    citation_id: str
    source_id: UUID
    source_name: str
    document_id: UUID
    document_name: str
    chunk_id: UUID
    chunk_index: int
    page: int | None
    section: str | None
    excerpt: str
    score: float
    semantic_score: float
    lexical_score: float


class SearchedSource(BaseModel):
    source_id: UUID
    source_name: str


class KnowledgeSearchResponse(BaseModel):
    query: str
    results: list[KnowledgeHit]
    sources_searched: list[SearchedSource]
    candidates: int
    truncated: bool
    insufficient: bool
    ranking: dict[str, float | int]


class AgentKnowledgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: UUID


class AgentKnowledgeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_enabled: bool


class AgentKnowledgeResponse(BaseModel):
    id: UUID
    agent_id: UUID
    source_id: UUID
    source_name: str
    source_status: KnowledgeSourceStatus
    document_count: int
    chunk_count: int
    is_enabled: bool
    created_at: datetime
