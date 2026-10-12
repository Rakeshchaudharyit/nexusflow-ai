"""Document ingestion, executed by the M7 worker for `knowledge_ingestion` jobs.

    read stored bytes → extract text → chunk → embed (batches) → replace chunks in one
    transaction together with the document, source and job rows

Idempotent by construction: the final transaction deletes the document's chunks and inserts
the new set (unique on document_id + chunk_index) while settling the job it owns, so retries,
duplicate deliveries and recovery restarts can never leave duplicate or partial chunks.
Cancellation is cooperative: checked between stages and embedding batches.
"""

import hashlib
import logging
from time import perf_counter
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.agents.errors import AgentRuntimeError
from app.core.config import Settings
from app.jobs.control import JobCancelled, JobControl, JobLost
from app.knowledge.chunking import chunk_sections
from app.knowledge.embeddings import EmbeddingProvider
from app.knowledge.extract import extract
from app.knowledge.lifecycle import lock_document, lock_source, now, refresh_source, settle_document
from app.knowledge.storage import FileStore, StorageUnavailable
from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentStatus,
    KnowledgeSource,
)

logger = logging.getLogger(__name__)
EMBED_BATCH = 64
GENERIC_FAILURE = "The document could not be ingested."


class IngestionError(AgentRuntimeError):
    code = "ingestion_failed"
    message = GENERIC_FAILURE


class KnowledgeIngestor:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        settings: Settings,
        embedder: EmbeddingProvider,
        store: FileStore,
    ):
        self._sessions = sessions
        self._settings = settings
        self._embedder = embedder
        self._store = store

    def execute(self, document_id: UUID, control: JobControl) -> None:
        started = perf_counter()
        with self._sessions() as db:
            document = db.get(KnowledgeDocument, document_id)
            source = document and db.get(KnowledgeSource, document.source_id)
            if document is None or source is None:
                raise IngestionError("The document no longer exists.", code="document_missing")
            organization_id, version = document.organization_id, document.version
            extension, name = document.extension, document.name
            source_id, source_name = source.id, source.name
        context = {
            "document_id": str(document_id),
            "source_id": str(source_id),
            "job": control.job_id,
        }
        try:
            control.checkpoint()
            try:
                data = self._store.read(organization_id, document_id, version, extension)
            except FileNotFoundError as error:
                raise IngestionError(
                    "The stored file is missing; upload the document again.", code="file_missing"
                ) from error
            except StorageUnavailable as error:
                raise IngestionError(
                    "Document storage is temporarily unavailable.", code="storage_unavailable"
                ) from error
            extraction = extract(extension, data)
            size, overlap = (
                self._settings.knowledge_chunk_size,
                self._settings.knowledge_chunk_overlap,
            )
            drafts = chunk_sections(extraction.sections, size, overlap)
            control.checkpoint()
            vectors: list[list[float]] = []
            for start in range(0, len(drafts), EMBED_BATCH):
                batch = drafts[start : start + EMBED_BATCH]
                # The heading is embedded with the chunk (not stored in it) to sharpen matches.
                vectors += self._embedder.embed(
                    [f"{d.heading}\n{d.text}" if d.heading else d.text for d in batch]
                )
                control.checkpoint()
            rows = [
                KnowledgeChunk(
                    organization_id=organization_id,
                    source_id=source_id,
                    document_id=document_id,
                    chunk_index=draft.index,
                    content=draft.text,
                    content_hash=hashlib.sha256(draft.text.encode()).hexdigest(),
                    char_count=len(draft.text),
                    token_estimate=max(1, len(draft.text) // 4),
                    metadata_json={
                        "page": draft.page,
                        "heading": draft.heading,
                        "document_name": name,
                        "source_name": source_name,
                        "chunk_index": draft.index,
                    },
                    embedding=vector,
                )
                for draft, vector in zip(drafts, vectors, strict=True)
            ]
            elapsed = round((perf_counter() - started) * 1000)
            with self._sessions() as db:
                source = lock_source(db, organization_id, source_id)
                document = lock_document(db, organization_id, document_id)
                control.settle(db, "completed")  # raises JobLost if this attempt lost the job
                if document is None or source is None or document.version != version:
                    db.rollback()
                    return
                db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
                db.add_all(rows)
                document.status = KnowledgeDocumentStatus.READY
                document.ingested_version = version
                document.chunk_count = len(rows)
                document.ingested_at = now()
                document.ingestion_ms = elapsed
                document.error_code = document.error_message = None
                document.extraction = {
                    "parser": extraction.parser,
                    "pages": extraction.pages,
                    "characters": extraction.chars,
                    "chunks": len(rows),
                    "chunk_size": size,
                    "chunk_overlap": overlap,
                }
                refresh_source(db, source)
                db.commit()
            self._store.prune(organization_id, document_id, version)
            logger.info(
                "Knowledge document ingested %s chunks=%s ms=%s", context, len(rows), elapsed
            )
        except JobCancelled:
            self._settle(control, organization_id, source_id, document_id, "cancelled")
        except JobLost:
            logger.warning("Ingestion %s: attempt no longer owns its job; stopping", context)
        except AgentRuntimeError as error:
            if control.cancel_requested():
                self._settle(control, organization_id, source_id, document_id, "cancelled")
            elif control.should_retry(error.code):
                self._settle(
                    control,
                    organization_id,
                    source_id,
                    document_id,
                    "retry",
                    error.code,
                    error.message,
                )
            else:
                self._settle(
                    control,
                    organization_id,
                    source_id,
                    document_id,
                    "failed",
                    error.code,
                    error.message,
                )
            logger.info("Knowledge ingestion %s ended: %s", context, error.code)
        except Exception as error:
            logger.error("Knowledge ingestion %s failed (%s)", context, type(error).__name__)
            self._settle(
                control,
                organization_id,
                source_id,
                document_id,
                "failed",
                "ingestion_failed",
                GENERIC_FAILURE,
            )

    def _settle(
        self,
        control: JobControl,
        organization_id: UUID,
        source_id: UUID,
        document_id: UUID,
        outcome: str,
        code: str | None = None,
        message: str | None = None,
    ) -> None:
        with self._sessions() as db:
            source = lock_source(db, organization_id, source_id)
            document = lock_document(db, organization_id, document_id)
            try:
                control.settle(db, outcome, code, message)
            except JobLost:
                db.rollback()
                return
            if document is not None:
                settle_document(document, outcome, code, message)
            if source is not None:
                refresh_source(db, source)
            db.commit()


def document_exists(db: Session, organization_id: UUID, document_id: UUID) -> bool:
    return (
        db.scalar(
            select(KnowledgeDocument.id).where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.organization_id == organization_id,
            )
        )
        is not None
    )
