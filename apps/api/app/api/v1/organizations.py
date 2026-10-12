from uuid import UUID

from fastapi import APIRouter

from app.api.dependencies import CurrentMembership, CurrentUser, Database
from app.schemas.auth import OrganizationCreate, OrganizationResponse
from app.services.organizations import (
    create_organization,
    get_membership,
    list_organizations,
    organization_response,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationResponse])
def organizations(user: CurrentUser, db: Database):
    return list_organizations(db, user.id)


@router.post("", response_model=OrganizationResponse, status_code=201)
def create(data: OrganizationCreate, user: CurrentUser, db: Database):
    return create_organization(db, user, data.name)


@router.get("/current", response_model=OrganizationResponse)
def current(membership: CurrentMembership, db: Database):
    return organization_response(db, membership)


@router.get("/{organization_id}", response_model=OrganizationResponse)
def organization(organization_id: UUID, user: CurrentUser, db: Database):
    return organization_response(db, get_membership(db, user.id, organization_id))
