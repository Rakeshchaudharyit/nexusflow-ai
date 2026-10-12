from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import CurrentMembership, Database
from app.memory import service
from app.models.memory import MemoryScope, MemorySource, MemoryType, ThreadStatus
from app.schemas.memory import (
    MemoryCreate,
    MemoryDeleted,
    MemoryResponse,
    MemoryUpdate,
    ThreadCreate,
    ThreadDetail,
    ThreadResponse,
    ThreadUpdate,
)

router = APIRouter(tags=["memory"])


@router.post("/threads", response_model=ThreadResponse, status_code=201)
def create_thread(data: ThreadCreate, membership: CurrentMembership, db: Database):
    return service.create_thread(db, membership, data)


@router.get("/threads", response_model=list[ThreadResponse])
def list_threads(
    membership: CurrentMembership,
    db: Database,
    status: ThreadStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_threads(db, membership.organization_id, status, limit)


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
def get_thread(thread_id: UUID, membership: CurrentMembership, db: Database):
    return service.get_thread_detail(db, membership.organization_id, thread_id)


@router.patch("/threads/{thread_id}", response_model=ThreadResponse)
def update_thread(thread_id: UUID, data: ThreadUpdate, membership: CurrentMembership, db: Database):
    return service.update_thread(db, membership, thread_id, data)


@router.get("/memory", response_model=list[MemoryResponse])
def list_memory(
    membership: CurrentMembership,
    db: Database,
    memory_type: MemoryType | None = None,
    scope: MemoryScope | None = None,
    thread_id: UUID | None = None,
    agent_id: UUID | None = None,
    active: bool | None = None,
    source_type: MemorySource | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    return service.list_memory(
        db,
        membership.organization_id,
        memory_type=memory_type,
        scope=scope,
        thread_id=thread_id,
        agent_id=agent_id,
        active=active,
        source_type=source_type,
        limit=limit,
    )


@router.post("/memory", response_model=MemoryResponse, status_code=201)
def create_memory(data: MemoryCreate, membership: CurrentMembership, db: Database):
    return service.create_memory(db, membership, data)


@router.get("/memory/{memory_id}", response_model=MemoryResponse)
def get_memory(memory_id: UUID, membership: CurrentMembership, db: Database):
    return service.entry_detail(db, service.get_entry(db, membership.organization_id, memory_id))


@router.patch("/memory/{memory_id}", response_model=MemoryResponse)
def update_memory(memory_id: UUID, data: MemoryUpdate, membership: CurrentMembership, db: Database):
    return service.update_memory(db, membership, memory_id, data)


@router.delete("/memory/{memory_id}", response_model=MemoryDeleted)
def delete_memory(memory_id: UUID, membership: CurrentMembership, db: Database):
    """Manual memory is deleted; run-derived memory is deactivated (provenance kept)."""
    return service.delete_memory(db, membership, memory_id)
