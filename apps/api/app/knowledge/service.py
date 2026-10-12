"""Knowledge APIs: sources, documents, re-indexing, search and agent grants.

Every query is scoped to the caller's organization; an id from another organization is
indistinguishable from a missing one (404). Parsing and embedding never happen here: uploads
are validated, stored and queued as `knowledge_ingestion` jobs for the M7 worker.
"""

import hashlib
import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import APIError
from app.jobs.service import JobQueue, create_job, deliver, latest_job
from app.knowledge.access import KNOWLEDGE_TOOL_KEY
from app.knowledge.embeddings import EmbeddingProvider
from app.knowledge.extract import KnowledgeFileError, check_content, file_type, safe_filename
from app.knowledge.lifecycle import lock_document, lock_source, now, refresh_source, settle_document
from app.knowledge.retrieval import search
from app.knowledge.storage import FileStore, StorageUnavailable
from app.models.agents import Agent
from app.models.identity import User
from app.models.jobs import ACTIVE_JOB_STATUSES, ExecutionJob, JobStatus, JobType
from app.models.knowledge import (
    AgentKnowledgeSource,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeSource,
    KnowledgeSourceStatus,
    KnowledgeSourceType,
)
from app.models.teams import AgentTool
from app.schemas.knowledge import (
    AgentKnowledgeResponse,
    ChunkPreview,
    DocumentCancelResult,
    DocumentUploadResult,
    IngestionInfo,
    KnowledgeDocumentDetail,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceDetail,
    KnowledgeSourceResponse,
    KnowledgeSourceUpdate,
    ReindexResult,
    SourceAgent,
)
from app.services.agents import get_agent

logger = logging.getLogger(__name__)
NOT_FOUND = ("knowledge_source_not_found", "Knowledge source not found.")
DOCUMENT_NOT_FOUND = ("knowledge_document_not_found", "Knowledge document not found.")
BUSY = APIError(
    409, "ingestion_in_progress", "Wait for ingestion to finish, or cancel it, and try again."
)


# --- sources -------------------------------------------------------------------------------


def get_source(db: Session, organization_id: UUID, source_id: UUID) -> KnowledgeSource:
    source = db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.id == source_id, KnowledgeSource.organization_id == organization_id
        )
    )
    if source is None:
        raise APIError(404, *NOT_FOUND)
    return source


def locked_source(db: Session, organization_id: UUID, source_id: UUID) -> KnowledgeSource:
    source = lock_source(db, organization_id, source_id)
    if source is None:
        raise APIError(404, *NOT_FOUND)
    return source


def agent_counts(db: Session, organization_id: UUID) -> dict[UUID, int]:
    return dict(
        db.execute(
            select(AgentKnowledgeSource.source_id, func.count())
            .where(
                AgentKnowledgeSource.organization_id == organization_id,
                AgentKnowledgeSource.is_enabled.is_(True),
            )
            .group_by(AgentKnowledgeSource.source_id)
        ).all()
    )


def source_response(source: KnowledgeSource, agent_count: int = 0) -> KnowledgeSourceResponse:
    response = KnowledgeSourceResponse.model_validate(source)
    response.agent_count = agent_count
    return response


def list_sources(
    db: Session, organization_id: UUID, status: KnowledgeSourceStatus | None = None
) -> list[KnowledgeSourceResponse]:
    query = select(KnowledgeSource).where(KnowledgeSource.organization_id == organization_id)
    if status is not None:
        query = query.where(KnowledgeSource.status == status)
    counts = agent_counts(db, organization_id)
    return [
        source_response(source, counts.get(source.id, 0))
        for source in db.scalars(query.order_by(KnowledgeSource.updated_at.desc()))
    ]


def create_source(
    db: Session, settings: Settings, organization_id: UUID, user: User, data: KnowledgeSourceCreate
) -> KnowledgeSourceResponse:
    provider = data.embedding_provider or settings.knowledge_embedding_provider
    if provider != settings.knowledge_embedding_provider:
        raise APIError(
            422,
            "embedding_provider_unavailable",
            f"Only the configured embedding provider ({settings.knowledge_embedding_provider}) "
            "is available.",
        )
    source = KnowledgeSource(
        organization_id=organization_id,
        name=data.name,
        description=data.description,
        source_type=data.source_type,
        created_by_user_id=user.id,
        embedding_provider=provider,
        embedding_model=settings.knowledge_embedding_model,
        embedding_dimension=settings.knowledge_embedding_dimension,
        chunking_strategy={
            "strategy": "structure_aware_recursive",
            "chunk_size": settings.knowledge_chunk_size,
            "chunk_overlap": settings.knowledge_chunk_overlap,
        },
        metadata_json={},
    )
    db.add(source)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise APIError(409, "knowledge_source_exists", "A source with this name exists.") from error
    return source_response(source)


def update_source(
    db: Session, organization_id: UUID, source_id: UUID, data: KnowledgeSourceUpdate
) -> KnowledgeSourceResponse:
    source = locked_source(db, organization_id, source_id)
    if data.name is not None:
        source.name = data.name
    if data.description is not None:
        source.description = data.description
    if data.archived is True and source.status != KnowledgeSourceStatus.ARCHIVED:
        if source.status == KnowledgeSourceStatus.PROCESSING:
            raise BUSY
        # Excluded from retrieval and agents immediately; documents and chunks are kept.
        source.status = KnowledgeSourceStatus.ARCHIVED
        source.archived_at = now()
    elif data.archived is False and source.status == KnowledgeSourceStatus.ARCHIVED:
        source.status = KnowledgeSourceStatus.DRAFT
        source.archived_at = None
        refresh_source(db, source)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise APIError(409, "knowledge_source_exists", "A source with this name exists.") from error
    return source_response(source, agent_counts(db, organization_id).get(source.id, 0))


def delete_source(db: Session, store: FileStore, organization_id: UUID, source_id: UUID) -> None:
    """Documents, chunks (vectors), agent grants and ingestion jobs go with the source
    (database cascades); stored files are removed after the commit."""
    source = locked_source(db, organization_id, source_id)
    if source.status == KnowledgeSourceStatus.PROCESSING:
        raise BUSY
    documents = list(
        db.scalars(select(KnowledgeDocument.id).where(KnowledgeDocument.source_id == source.id))
    )
    db.delete(source)
    db.commit()
    for document_id in documents:
        store.delete_document(organization_id, document_id)


def source_detail(db: Session, organization_id: UUID, source_id: UUID) -> KnowledgeSourceDetail:
    source = get_source(db, organization_id, source_id)
    documents = list(
        db.scalars(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.source_id == source.id,
                KnowledgeDocument.organization_id == organization_id,
            )
            .order_by(KnowledgeDocument.created_at, KnowledgeDocument.name)
        )
    )
    tool_agents = set(
        db.scalars(
            select(AgentTool.agent_id).where(
                AgentTool.organization_id == organization_id,
                AgentTool.tool_key == KNOWLEDGE_TOOL_KEY,
                AgentTool.is_enabled.is_(True),
            )
        )
    )
    agents = [
        SourceAgent(
            agent_id=grant.agent_id,
            agent_name=name,
            is_enabled=grant.is_enabled,
            has_search_tool=grant.agent_id in tool_agents,
        )
        for grant, name in db.execute(
            select(AgentKnowledgeSource, Agent.name)
            .join(
                Agent,
                (Agent.id == AgentKnowledgeSource.agent_id)
                & (Agent.organization_id == AgentKnowledgeSource.organization_id),
            )
            .where(
                AgentKnowledgeSource.source_id == source.id,
                AgentKnowledgeSource.organization_id == organization_id,
            )
            .order_by(Agent.name)
        )
    ]
    base = source_response(source, sum(1 for agent in agents if agent.is_enabled))
    return KnowledgeSourceDetail(
        **base.model_dump(),
        documents=[document_response(db, document) for document in documents],
        agents=agents,
    )


# --- documents -----------------------------------------------------------------------------


def ingestion_info(db: Session, document: KnowledgeDocument) -> IngestionInfo | None:
    job = latest_job(db, document.organization_id, knowledge_document_id=document.id)
    if job is None:
        return None
    return IngestionInfo(
        job_id=job.id,
        status=job.status,
        attempt=job.attempt,
        max_attempts=job.max_attempts,
        cancellation_requested=job.cancellation_requested_at is not None,
        error_code=job.error_code,
        next_retry_at=job.next_retry_at,
    )


def document_response(db: Session, document: KnowledgeDocument) -> KnowledgeDocumentResponse:
    response = KnowledgeDocumentResponse.model_validate(document)
    response.ingestion = ingestion_info(db, document)
    return response


def active_jobs(db: Session, organization_id: UUID, document_id: UUID) -> list[ExecutionJob]:
    return list(
        db.scalars(
            select(ExecutionJob)
            .where(
                ExecutionJob.knowledge_document_id == document_id,
                ExecutionJob.organization_id == organization_id,
                ExecutionJob.status.in_(ACTIVE_JOB_STATUSES),
            )
            .order_by(ExecutionJob.id)
            .with_for_update()
        )
    )


def _queue_ingestion(db: Session, settings: Settings, document: KnowledgeDocument) -> ExecutionJob:
    document.status = KnowledgeDocumentStatus.PROCESSING
    document.error_code = document.error_message = None
    return create_job(
        db,
        settings,
        organization_id=document.organization_id,
        job_type=JobType.KNOWLEDGE_INGESTION,
        knowledge_document_id=document.id,
    )


def add_document(
    db: Session,
    settings: Settings,
    store: FileStore,
    queue: JobQueue,
    organization_id: UUID,
    user: User,
    source_id: UUID,
    *,
    name: str,
    declared_type: str | None,
    data: bytes,
    text_document: bool,
) -> DocumentUploadResult:
    """Validate, store and queue one document. Same content already in the source: 409
    duplicate_document. Same name, new content: the document is replaced (version + 1) and
    re-ingested; its previous chunks keep serving until the new ones replace them."""
    source = locked_source(db, organization_id, source_id)
    if source.status == KnowledgeSourceStatus.ARCHIVED:
        raise APIError(409, "source_archived", "Archived sources do not accept documents.")
    expected = KnowledgeSourceType.TEXT if text_document else KnowledgeSourceType.FILE
    if source.source_type != expected:
        raise APIError(
            422,
            "wrong_source_type",
            "Text sources take pasted text; file sources take uploaded files.",
        )
    limit = settings.knowledge_max_file_mb * 1024 * 1024
    if len(data) > limit:
        raise APIError(
            413, "file_too_large", f"Files may be at most {settings.knowledge_max_file_mb} MB."
        )
    try:
        name = safe_filename(name)
        extension, mime_type = file_type(name, declared_type)
        check_content(extension, data)
    except KnowledgeFileError as error:
        raise APIError(422, error.code, error.message) from error
    checksum = hashlib.sha256(data).hexdigest()
    duplicate = db.scalar(
        select(KnowledgeDocument.name).where(
            KnowledgeDocument.source_id == source.id,
            KnowledgeDocument.organization_id == organization_id,
            KnowledgeDocument.checksum == checksum,
        )
    )
    if duplicate is not None:
        raise APIError(
            409,
            "duplicate_document",
            f"This content is already in the source as '{duplicate}'.",
        )
    document = db.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.source_id == source.id,
            KnowledgeDocument.organization_id == organization_id,
            KnowledgeDocument.name == name,
        )
        .with_for_update()
    )
    outcome = "replaced" if document is not None else "created"
    if document is not None:
        if active_jobs(db, organization_id, document.id):
            raise BUSY
        document.version += 1
        document.checksum, document.size_bytes = checksum, len(data)
        document.extension, document.mime_type = extension, mime_type
    else:
        document = KnowledgeDocument(
            organization_id=organization_id,
            source_id=source.id,
            name=name,
            extension=extension,
            mime_type=mime_type,
            checksum=checksum,
            size_bytes=len(data),
            version=1,
            created_by_user_id=user.id,
        )
        db.add(document)
        db.flush()
    try:
        store.write(organization_id, document.id, document.version, extension, data)
    except StorageUnavailable as error:
        db.rollback()
        raise APIError(
            503, "storage_unavailable", "Document storage is unavailable. Try again shortly."
        ) from error
    job = _queue_ingestion(db, settings, document)
    refresh_source(db, source)
    db.commit()
    logger.info(
        "Knowledge document queued source=%s document=%s job=%s bytes=%s",
        source.id,
        document.id,
        job.id,
        len(data),
    )
    deliver(db, queue, job.id)
    db.expire_all()  # inline/test delivery may already have finished the job
    return DocumentUploadResult(document=document_response(db, document), outcome=outcome)


def reindex_source(
    db: Session, settings: Settings, queue: JobQueue, organization_id: UUID, source_id: UUID
) -> ReindexResult:
    """Re-extract, re-chunk and re-embed every document through the worker. Each document's
    chunks are replaced in one transaction, so vectors are never duplicated."""
    source = locked_source(db, organization_id, source_id)
    if source.status == KnowledgeSourceStatus.ARCHIVED:
        raise APIError(409, "source_archived", "Unarchive the source before re-indexing it.")
    jobs, skipped = [], 0
    for document in db.scalars(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.source_id == source.id,
            KnowledgeDocument.organization_id == organization_id,
        )
        .order_by(KnowledgeDocument.created_at, KnowledgeDocument.id)
        .with_for_update()
    ):
        if active_jobs(db, organization_id, document.id):
            skipped += 1
            continue
        jobs.append(_queue_ingestion(db, settings, document).id)
    refresh_source(db, source)
    db.commit()
    for job_id in jobs:
        deliver(db, queue, job_id)
    db.expire_all()
    return ReindexResult(
        source=source_response(source, agent_counts(db, organization_id).get(source.id, 0)),
        queued=len(jobs),
        skipped=skipped,
    )


def get_document(db: Session, organization_id: UUID, document_id: UUID) -> KnowledgeDocument:
    document = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.organization_id == organization_id,
        )
    )
    if document is None:
        raise APIError(404, *DOCUMENT_NOT_FOUND)
    return document


def list_documents(
    db: Session, organization_id: UUID, source_id: UUID
) -> list[KnowledgeDocumentResponse]:
    return source_detail(db, organization_id, source_id).documents


def document_detail(
    db: Session, organization_id: UUID, document_id: UUID
) -> KnowledgeDocumentDetail:
    document = get_document(db, organization_id, document_id)
    source = get_source(db, organization_id, document.source_id)
    chunks = db.scalars(
        select(KnowledgeChunk)
        .where(
            KnowledgeChunk.document_id == document.id,
            KnowledgeChunk.organization_id == organization_id,
        )
        .order_by(KnowledgeChunk.chunk_index)
        .limit(100)
    )
    return KnowledgeDocumentDetail(
        **document_response(db, document).model_dump(),
        source_name=source.name,
        source_status=source.status,
        chunks=[
            ChunkPreview(
                id=chunk.id,
                chunk_index=chunk.chunk_index,
                page=(chunk.metadata_json or {}).get("page"),
                section=(chunk.metadata_json or {}).get("heading"),
                char_count=chunk.char_count,
                token_estimate=chunk.token_estimate,
                preview=chunk.content[:240],
            )
            for chunk in chunks
        ],
    )


def cancel_document(db: Session, organization_id: UUID, document_id: UUID) -> DocumentCancelResult:
    """M7 cooperative cancellation: a waiting job stops now, a running one at its next stage."""
    document = get_document(db, organization_id, document_id)
    source = locked_source(db, organization_id, document.source_id)
    document = lock_document(db, organization_id, document_id)
    jobs = active_jobs(db, organization_id, document.id)
    if not jobs:
        raise APIError(409, "nothing_to_cancel", "This document is not being ingested.")
    moment, outcome = now(), "cancelled"
    for job in jobs:
        job.cancellation_requested_at = job.cancellation_requested_at or moment
        if job.status == JobStatus.RUNNING:
            outcome = "cancellation_requested"
            continue
        job.status, job.completed_at = JobStatus.CANCELLED, moment
        job.error_code, job.error_message = "cancelled", "Ingestion was cancelled."
    if outcome == "cancelled":
        settle_document(document, "cancelled")
        refresh_source(db, source)
    db.commit()
    return DocumentCancelResult(document=document_response(db, document), outcome=outcome)


def delete_document(
    db: Session, store: FileStore, organization_id: UUID, document_id: UUID
) -> None:
    document = get_document(db, organization_id, document_id)
    source = locked_source(db, organization_id, document.source_id)
    document = lock_document(db, organization_id, document_id)
    if active_jobs(db, organization_id, document.id):
        raise BUSY
    db.delete(document)  # chunks and jobs cascade
    refresh_source(db, source)
    db.commit()
    store.delete_document(organization_id, document_id)


# --- search --------------------------------------------------------------------------------


def search_knowledge(
    db: Session,
    settings: Settings,
    embedder: EmbeddingProvider,
    organization_id: UUID,
    data: KnowledgeSearchRequest,
) -> KnowledgeSearchResponse:
    """Debug/test search over this organization's sources (all non-archived by default)."""
    if data.source_ids:
        source_ids = list(data.source_ids)
    else:
        source_ids = list(
            db.scalars(
                select(KnowledgeSource.id).where(KnowledgeSource.organization_id == organization_id)
            )
        )
    retrieval = search(
        db,
        settings,
        embedder,
        organization_id=organization_id,
        query=data.query,
        source_ids=source_ids,
        top_k=data.top_k,
    )
    return KnowledgeSearchResponse(
        query=retrieval.query,
        results=[
            {
                **hit.citation(),
                "semantic_score": hit.semantic_score,
                "lexical_score": hit.lexical_score,
            }
            for hit in retrieval.hits
        ],
        sources_searched=retrieval.sources_searched,
        candidates=retrieval.candidates,
        truncated=retrieval.truncated,
        insufficient=retrieval.insufficient,
        ranking={
            "semantic_weight": settings.knowledge_semantic_weight,
            "lexical_weight": settings.knowledge_lexical_weight,
            "min_score": settings.knowledge_min_score,
            "top_k": data.top_k or settings.knowledge_top_k,
        },
    )


# --- agent grants --------------------------------------------------------------------------


def grant_response(grant: AgentKnowledgeSource, source: KnowledgeSource) -> AgentKnowledgeResponse:
    return AgentKnowledgeResponse(
        id=grant.id,
        agent_id=grant.agent_id,
        source_id=source.id,
        source_name=source.name,
        source_status=source.status,
        document_count=source.document_count,
        chunk_count=source.chunk_count,
        is_enabled=grant.is_enabled,
        created_at=grant.created_at,
    )


def agent_knowledge(
    db: Session, organization_id: UUID, agent_id: UUID
) -> list[AgentKnowledgeResponse]:
    agent = get_agent(db, organization_id, agent_id)
    return [
        grant_response(grant, source)
        for grant, source in db.execute(
            select(AgentKnowledgeSource, KnowledgeSource)
            .join(
                KnowledgeSource,
                (KnowledgeSource.id == AgentKnowledgeSource.source_id)
                & (KnowledgeSource.organization_id == AgentKnowledgeSource.organization_id),
            )
            .where(
                AgentKnowledgeSource.agent_id == agent.id,
                AgentKnowledgeSource.organization_id == organization_id,
            )
            .order_by(KnowledgeSource.name)
        )
    ]


def assign_source(
    db: Session, organization_id: UUID, agent_id: UUID, source_id: UUID
) -> AgentKnowledgeResponse:
    agent = get_agent(db, organization_id, agent_id)
    source = get_source(db, organization_id, source_id)
    if source.status in (KnowledgeSourceStatus.ARCHIVED, KnowledgeSourceStatus.FAILED):
        raise APIError(
            409,
            "source_not_assignable",
            "Archived or failed sources cannot be assigned to agents.",
        )
    grant = AgentKnowledgeSource(
        organization_id=organization_id, agent_id=agent.id, source_id=source.id
    )
    db.add(grant)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise APIError(
            409, "knowledge_already_assigned", "This source is already assigned."
        ) from error
    return grant_response(grant, source)


def _grant(db: Session, organization_id: UUID, agent_id: UUID, source_id: UUID):
    get_agent(db, organization_id, agent_id)
    row = db.execute(
        select(AgentKnowledgeSource, KnowledgeSource)
        .join(
            KnowledgeSource,
            (KnowledgeSource.id == AgentKnowledgeSource.source_id)
            & (KnowledgeSource.organization_id == AgentKnowledgeSource.organization_id),
        )
        .where(
            AgentKnowledgeSource.agent_id == agent_id,
            AgentKnowledgeSource.source_id == source_id,
            AgentKnowledgeSource.organization_id == organization_id,
        )
    ).first()
    if row is None:
        raise APIError(404, "knowledge_assignment_not_found", "Knowledge assignment not found.")
    return row


def update_grant(
    db: Session, organization_id: UUID, agent_id: UUID, source_id: UUID, is_enabled: bool
) -> AgentKnowledgeResponse:
    grant, source = _grant(db, organization_id, agent_id, source_id)
    if is_enabled and source.status in (
        KnowledgeSourceStatus.ARCHIVED,
        KnowledgeSourceStatus.FAILED,
    ):
        raise APIError(
            409, "source_not_assignable", "Archived or failed sources cannot be enabled."
        )
    grant.is_enabled = is_enabled
    db.commit()
    return grant_response(grant, source)


def remove_grant(db: Session, organization_id: UUID, agent_id: UUID, source_id: UUID) -> None:
    grant, _ = _grant(db, organization_id, agent_id, source_id)
    db.delete(grant)
    db.commit()
