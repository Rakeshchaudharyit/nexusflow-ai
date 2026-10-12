from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import (
    CurrentMembership,
    CurrentUser,
    Database,
    Mcp,
    McpUrls,
    require_organization_role,
)
from app.models.identity import OrganizationMembership, Role
from app.schemas.mcp import (
    McpConnectionTest,
    McpDiscoveryResponse,
    McpServerCreate,
    McpServerResponse,
    McpServerUpdate,
    McpToolResponse,
    McpToolUpdate,
)
from app.services import mcp_servers as service

router = APIRouter(prefix="/mcp-servers", tags=["mcp"])
Manager = Annotated[
    OrganizationMembership, Depends(require_organization_role(Role.OWNER, Role.ADMIN))
]


@router.post("", response_model=McpServerResponse, status_code=201)
def create_server(
    data: McpServerCreate, membership: Manager, user: CurrentUser, db: Database, urls: McpUrls
):
    return service.create_server(db, membership.organization_id, user, data, urls)


@router.get("", response_model=list[McpServerResponse])
def list_servers(membership: CurrentMembership, db: Database):
    return service.list_servers(db, membership.organization_id)


@router.get("/{server_id}", response_model=McpServerResponse)
def get_server(server_id: UUID, membership: CurrentMembership, db: Database):
    return service.describe(db, service.get_server(db, membership.organization_id, server_id))


@router.patch("/{server_id}", response_model=McpServerResponse)
def update_server(
    server_id: UUID, data: McpServerUpdate, membership: Manager, db: Database, urls: McpUrls
):
    return service.update_server(db, membership.organization_id, server_id, data, urls)


@router.post("/{server_id}/test", response_model=McpConnectionTest)
def test_connection(
    server_id: UUID, membership: Manager, db: Database, mcp: Mcp, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    return service.check_connection(db, membership.organization_id, server_id, mcp)


@router.post("/{server_id}/discover", response_model=McpDiscoveryResponse)
def discover_tools(server_id: UUID, membership: Manager, db: Database, mcp: Mcp):
    return service.discover_tools(db, membership.organization_id, server_id, mcp)


@router.get("/{server_id}/tools", response_model=list[McpToolResponse])
def list_tools(server_id: UUID, membership: CurrentMembership, db: Database):
    return service.list_tools(db, membership.organization_id, server_id)


@router.patch("/{server_id}/tools/{tool_id}", response_model=McpToolResponse)
def update_tool(
    server_id: UUID, tool_id: UUID, data: McpToolUpdate, membership: Manager, db: Database
):
    return service.update_tool(db, membership.organization_id, server_id, tool_id, data.is_enabled)
