from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.api.dependencies import (
    CurrentMembership,
    CurrentUser,
    Database,
    JobQueueDep,
    require_organization_role,
)
from app.core.errors import APIError
from app.jobs import runtimes
from app.knowledge import service
from app.knowledge.embeddings import create_embedder
from app.models.identity import OrganizationMembership, Role
from app.models.knowledge import KnowledgeSourceStatus
from app.schemas.knowledge import (
    AgentKnowledgeCreate,
    AgentKnowledgeResponse,
    AgentKnowledgeUpdate,
    DocumentCancelResult,
    DocumentUploadResult,
    KnowledgeDocumentDetail,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceDetail,
    KnowledgeSourceResponse,
    KnowledgeSourceUpdate,
    ReindexResult,
    TextDocumentCreate,
)

router = APIRouter(tags=["knowledge"])
KnowledgeManager = Annotated[
    OrganizationMembership, Depends(require_organization_role(Role.OWNER, Role.ADMIN))
]
# Multipart framing and the small JSON envelope around a file stay under this allowance.
FORM_OVERHEAD = 64 * 1024


def store(request: Request):
    return runtimes.knowledge_store(request.app.state.settings)


@router.get("/knowledge-sources", response_model=list[KnowledgeSourceResponse])
def list_sources(
    membership: CurrentMembership, db: Database, status: KnowledgeSourceStatus | None = None
):
    return service.list_sources(db, membership.organization_id, status)


@router.post("/knowledge-sources", response_model=KnowledgeSourceResponse, status_code=201)
def create_source(
    data: KnowledgeSourceCreate,
    membership: KnowledgeManager,
    user: CurrentUser,
    db: Database,
    request: Request,
):
    return service.create_source(
        db, request.app.state.settings, membership.organization_id, user, data
    )


@router.get("/knowledge-sources/{source_id}", response_model=KnowledgeSourceDetail)
def get_source(source_id: UUID, membership: CurrentMembership, db: Database, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return service.source_detail(db, membership.organization_id, source_id)


@router.patch("/knowledge-sources/{source_id}", response_model=KnowledgeSourceResponse)
def update_source(
    source_id: UUID, data: KnowledgeSourceUpdate, membership: KnowledgeManager, db: Database
):
    return service.update_source(db, membership.organization_id, source_id, data)


@router.delete("/knowledge-sources/{source_id}", status_code=204)
def delete_source(source_id: UUID, membership: KnowledgeManager, db: Database, request: Request):
    service.delete_source(db, store(request), membership.organization_id, source_id)


@router.get(
    "/knowledge-sources/{source_id}/documents", response_model=list[KnowledgeDocumentResponse]
)
def list_documents(source_id: UUID, membership: CurrentMembership, db: Database):
    return service.list_documents(db, membership.organization_id, source_id)


@router.post(
    "/knowledge-sources/{source_id}/documents",
    response_model=DocumentUploadResult,
    status_code=201,
)
async def add_document(
    source_id: UUID,
    request: Request,
    membership: KnowledgeManager,
    user: CurrentUser,
    db: Database,
    queue: JobQueueDep,
):
    """multipart/form-data with one `file` (file sources), or JSON {name, content} (text
    sources). The request only validates, stores and queues; the worker ingests."""
    settings = request.app.state.settings
    limit = settings.knowledge_max_file_mb * 1024 * 1024
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > limit + FORM_OVERHEAD:
        raise APIError(
            413, "file_too_large", f"Files may be at most {settings.knowledge_max_file_mb} MB."
        )
    # Bound the wire body before Starlette's multipart parser can spool an oversized
    # chunked upload. Cache the bounded bytes using a new Request's receive channel.
    wire = bytearray()
    async for chunk in request.stream():
        if len(wire) + len(chunk) > limit + FORM_OVERHEAD:
            raise APIError(413, "file_too_large", "Upload exceeds the configured size limit.")
        wire.extend(chunk)

    async def receive_body():
        return {"type": "http.request", "body": bytes(wire), "more_body": False}

    request = Request(request.scope, receive=receive_body)
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form(max_files=1, max_fields=2)
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise APIError(422, "file_required", "Attach one file in the 'file' field.")
        data = await upload.read(limit + 1)
        name, declared, text_document = upload.filename or "", upload.content_type, False
        await form.close()
    elif content_type.startswith("application/json"):
        try:
            body = TextDocumentCreate.model_validate_json(await request.body())
        except ValidationError as error:
            raise APIError(422, "validation_error", "Provide name and content.") from error
        name = body.name if "." in body.name else f"{body.name}.txt"
        data, declared, text_document = body.content.encode(), None, True
    else:
        raise APIError(415, "unsupported_media_type", "Send multipart/form-data or JSON.")
    return await run_in_threadpool(
        service.add_document,
        db,
        settings,
        store(request),
        queue,
        membership.organization_id,
        user,
        source_id,
        name=name,
        declared_type=declared,
        data=data,
        text_document=text_document,
    )


@router.post("/knowledge-sources/{source_id}/reindex", response_model=ReindexResult)
def reindex_source(
    source_id: UUID,
    membership: KnowledgeManager,
    db: Database,
    queue: JobQueueDep,
    request: Request,
):
    return service.reindex_source(
        db, request.app.state.settings, queue, membership.organization_id, source_id
    )


@router.get("/knowledge-documents/{document_id}", response_model=KnowledgeDocumentDetail)
def get_document(
    document_id: UUID, membership: CurrentMembership, db: Database, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    return service.document_detail(db, membership.organization_id, document_id)


@router.post("/knowledge-documents/{document_id}/cancel", response_model=DocumentCancelResult)
def cancel_document(document_id: UUID, membership: KnowledgeManager, db: Database):
    return service.cancel_document(db, membership.organization_id, document_id)


@router.delete("/knowledge-documents/{document_id}", status_code=204)
def delete_document(
    document_id: UUID, membership: KnowledgeManager, db: Database, request: Request
):
    service.delete_document(db, store(request), membership.organization_id, document_id)


@router.post("/knowledge/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    data: KnowledgeSearchRequest, membership: CurrentMembership, db: Database, request: Request
):
    settings = request.app.state.settings
    return service.search_knowledge(
        db, settings, create_embedder(settings), membership.organization_id, data
    )


@router.get("/agents/{agent_id}/knowledge", response_model=list[AgentKnowledgeResponse])
def list_agent_knowledge(agent_id: UUID, membership: CurrentMembership, db: Database):
    return service.agent_knowledge(db, membership.organization_id, agent_id)


@router.post("/agents/{agent_id}/knowledge", response_model=AgentKnowledgeResponse, status_code=201)
def assign_knowledge(
    agent_id: UUID, data: AgentKnowledgeCreate, membership: KnowledgeManager, db: Database
):
    return service.assign_source(db, membership.organization_id, agent_id, data.source_id)


@router.patch("/agents/{agent_id}/knowledge/{source_id}", response_model=AgentKnowledgeResponse)
def update_agent_knowledge(
    agent_id: UUID,
    source_id: UUID,
    data: AgentKnowledgeUpdate,
    membership: KnowledgeManager,
    db: Database,
):
    return service.update_grant(
        db, membership.organization_id, agent_id, source_id, data.is_enabled
    )


@router.delete("/agents/{agent_id}/knowledge/{source_id}", status_code=204)
def remove_agent_knowledge(
    agent_id: UUID, source_id: UUID, membership: KnowledgeManager, db: Database
):
    service.remove_grant(db, membership.organization_id, agent_id, source_id)
