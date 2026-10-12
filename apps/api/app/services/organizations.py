import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.models.identity import Organization, OrganizationMembership, Role, User
from app.schemas.auth import OrganizationResponse, UserResponse


def add_owned_organization(db: Session, user: User, name: str) -> Organization:
    identifier = uuid4()
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:100] or "workspace"
    organization = Organization(
        id=identifier, name=name, slug=f"{stem}-{identifier.hex}", created_by_user_id=user.id
    )
    db.add(organization)
    db.flush()
    db.add(OrganizationMembership(organization_id=identifier, user_id=user.id, role=Role.OWNER))
    db.flush()
    return organization


def list_organizations(db: Session, user_id: UUID) -> list[OrganizationResponse]:
    rows = db.execute(
        select(Organization, OrganizationMembership.role)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Organization.id)
        .where(OrganizationMembership.user_id == user_id)
        .order_by(Organization.created_at, Organization.id)
    )
    return [
        OrganizationResponse(id=org.id, name=org.name, slug=org.slug, role=role)
        for org, role in rows
    ]


def user_response(db: Session, user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        is_verified=user.is_verified,
        organizations=list_organizations(db, user.id),
    )


def get_membership(db: Session, user_id: UUID, organization_id: UUID) -> OrganizationMembership:
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.organization_id == organization_id,
        )
    )
    if membership is None:
        raise APIError(404, "organization_not_found", "Organization not found.")
    return membership


def organization_response(db: Session, membership: OrganizationMembership) -> OrganizationResponse:
    organization = db.get(Organization, membership.organization_id)
    return OrganizationResponse(
        id=organization.id, name=organization.name, slug=organization.slug, role=membership.role
    )


def create_organization(db: Session, user: User, name: str) -> OrganizationResponse:
    organization = add_owned_organization(db, user, name)
    db.commit()
    return OrganizationResponse(
        id=organization.id, name=organization.name, slug=organization.slug, role=Role.OWNER
    )
