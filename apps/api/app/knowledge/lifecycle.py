"""Document and source state transitions, shared by the API, the ingestor and job recovery.

Lock order everywhere: source -> document -> job.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.knowledge import (
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeSource,
    KnowledgeSourceStatus,
)

# Documents whose stored chunks may be searched. A processing document keeps serving its
# previous version until the new chunks replace it in one transaction.
SEARCHABLE = (KnowledgeDocumentStatus.READY, KnowledgeDocumentStatus.PROCESSING)


def lock_source(db: Session, organization_id: UUID, source_id: UUID) -> KnowledgeSource | None:
    return db.scalar(
        select(KnowledgeSource)
        .where(KnowledgeSource.id == source_id, KnowledgeSource.organization_id == organization_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def lock_document(
    db: Session, organization_id: UUID, document_id: UUID
) -> KnowledgeDocument | None:
    return db.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.organization_id == organization_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def refresh_source(db: Session, source: KnowledgeSource) -> None:
    """Recompute counts and the aggregate status from the source's documents."""
    db.flush()
    rows = db.execute(
        select(
            KnowledgeDocument.status,
            func.count(),
            func.coalesce(func.sum(KnowledgeDocument.chunk_count), 0),
            func.max(KnowledgeDocument.ingested_at),
        )
        .where(
            KnowledgeDocument.source_id == source.id,
            KnowledgeDocument.organization_id == source.organization_id,
        )
        .group_by(KnowledgeDocument.status)
    ).all()
    by_status = {status: count for status, count, _, _ in rows}
    source.document_count = sum(by_status.values())
    source.chunk_count = int(sum(chunks for status, _, chunks, _ in rows if status in SEARCHABLE))
    latest = [moment for *_, moment in rows if moment is not None]
    source.last_ingested_at = max(latest) if latest else source.last_ingested_at
    if source.status == KnowledgeSourceStatus.ARCHIVED:
        return
    if not by_status:
        source.status = KnowledgeSourceStatus.DRAFT
    elif by_status.get(KnowledgeDocumentStatus.PROCESSING):
        source.status = KnowledgeSourceStatus.PROCESSING
    elif by_status.get(KnowledgeDocumentStatus.READY):
        source.status = KnowledgeSourceStatus.READY
    else:
        source.status = KnowledgeSourceStatus.FAILED


def settle_document(
    document: KnowledgeDocument, outcome: str, code: str | None = None, message: str | None = None
) -> None:
    """Apply a job outcome that did not store new chunks: failed, cancelled or retrying."""
    if outcome == "retry":
        # Still processing; the error explains the wait until the next attempt.
        document.error_code, document.error_message = code, message
        return
    if outcome == "cancelled":
        # Chunks of the current content survive a cancelled re-index; otherwise nothing usable.
        current = document.ingested_version == document.version and document.chunk_count > 0
        document.status = (
            KnowledgeDocumentStatus.READY if current else KnowledgeDocumentStatus.CANCELLED
        )
        document.error_code, document.error_message = (
            (None, None) if current else ("cancelled", "Ingestion was cancelled.")
        )
        return
    document.status = KnowledgeDocumentStatus.FAILED
    document.error_code, document.error_message = code, message


def now() -> datetime:
    return datetime.now(UTC)
