"""Tenant-scoped MCP server registry operations.

Every lookup filters by the caller's verified organization. Network calls happen only through
McpClient, and no database transaction is held open while a call is in flight.
"""

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.mcp.client import McpClient
from app.mcp.discovery import reconcile_tools
from app.mcp.errors import McpError, McpUrlRejected
from app.mcp.registry import record_failure, record_reachable, tool_key
from app.mcp.urls import UrlPolicy, validate_server_url
from app.models.identity import User
from app.models.mcp import McpServer, McpServerStatus, McpTool, McpTransport
from app.schemas.mcp import (
    McpConnectionError,
    McpConnectionTest,
    McpDiscoveryResponse,
    McpServerCreate,
    McpServerResponse,
    McpServerUpdate,
    McpToolResponse,
)
from app.services.agents import next_slug, slugify


def checked_url(url: str, policy: UrlPolicy) -> str:
    try:
        return validate_server_url(url, policy)
    except McpUrlRejected as error:
        raise APIError(422, error.code, error.message) from error


def tool_counts(db: Session, organization_id: UUID, server_ids: list[UUID]) -> dict[UUID, int]:
    rows = db.execute(
        select(McpTool.mcp_server_id, func.count())
        .where(
            McpTool.organization_id == organization_id,
            McpTool.mcp_server_id.in_(server_ids),
            McpTool.is_available.is_(True),
        )
        .group_by(McpTool.mcp_server_id)
    )
    return {server_id: count for server_id, count in rows}


def server_response(server: McpServer, tool_count: int) -> McpServerResponse:
    return McpServerResponse(
        id=server.id,
        organization_id=server.organization_id,
        name=server.name,
        slug=server.slug,
        description=server.description,
        transport=server.transport,
        url=server.url,
        status=server.status,
        is_enabled=server.is_enabled,
        tool_count=tool_count,
        created_by_user_id=server.created_by_user_id,
        last_connected_at=server.last_connected_at,
        last_discovered_at=server.last_discovered_at,
        last_error_code=server.last_error_code,
        last_error_message=server.last_error_message,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


def tool_response(server: McpServer, tool: McpTool) -> McpToolResponse:
    return McpToolResponse(
        id=tool.id,
        mcp_server_id=tool.mcp_server_id,
        name=tool.name,
        tool_key=tool_key(server.slug, tool.name),
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        is_enabled=tool.is_enabled,
        is_available=tool.is_available,
        discovered_at=tool.discovered_at,
    )


def describe(db: Session, server: McpServer) -> McpServerResponse:
    counts = tool_counts(db, server.organization_id, [server.id])
    return server_response(server, counts.get(server.id, 0))


def get_server(db: Session, organization_id: UUID, server_id: UUID) -> McpServer:
    server = db.scalar(
        select(McpServer).where(
            McpServer.id == server_id, McpServer.organization_id == organization_id
        )
    )
    if server is None:
        raise APIError(404, "mcp_server_not_found", "MCP server not found.")
    return server


def create_server(
    db: Session, organization_id: UUID, user: User, data: McpServerCreate, policy: UrlPolicy
) -> McpServerResponse:
    url = checked_url(data.url, policy)
    base = slugify(data.name, "mcp-server")
    for slug in (next_slug(db, McpServer, organization_id, base), f"{base}-{uuid4().hex[:8]}"):
        server = McpServer(
            organization_id=organization_id,
            name=data.name,
            slug=slug,
            description=data.description,
            transport=McpTransport(data.transport),
            url=url,
            created_by_user_id=user.id,
        )
        db.add(server)
        try:
            db.commit()
            return server_response(server, 0)
        except IntegrityError:
            db.rollback()
    raise APIError(409, "mcp_server_slug_conflict", "Could not allocate a unique server slug.")


def list_servers(db: Session, organization_id: UUID) -> list[McpServerResponse]:
    servers = list(
        db.scalars(
            select(McpServer)
            .where(McpServer.organization_id == organization_id)
            .order_by(McpServer.created_at, McpServer.id)
        )
    )
    counts = tool_counts(db, organization_id, [server.id for server in servers])
    return [server_response(server, counts.get(server.id, 0)) for server in servers]


def update_server(
    db: Session, organization_id: UUID, server_id: UUID, data: McpServerUpdate, policy: UrlPolicy
) -> McpServerResponse:
    server = get_server(db, organization_id, server_id)
    changes = data.model_dump(exclude_unset=True)
    if "url" in changes:
        url = checked_url(changes.pop("url"), policy)
        if url != server.url:
            # A different endpoint invalidates everything learned about the old one.
            server.url = url
            server.status = McpServerStatus.PENDING
            server.last_connected_at = None
            server.last_discovered_at = None
            server.last_error_code = server.last_error_message = None
            for tool in db.scalars(
                select(McpTool).where(
                    McpTool.mcp_server_id == server.id,
                    McpTool.organization_id == organization_id,
                )
            ):
                tool.is_available = False
    if "is_enabled" in changes:
        enabled = changes.pop("is_enabled")
        if enabled != server.is_enabled:
            server.is_enabled = enabled
            server.status = McpServerStatus.PENDING if enabled else McpServerStatus.DISABLED
    for field, value in changes.items():
        setattr(server, field, value)
    db.commit()
    return describe(db, server)


def usable_server(db: Session, organization_id: UUID, server_id: UUID) -> McpServer:
    server = get_server(db, organization_id, server_id)
    if not server.is_enabled:
        raise APIError(409, "mcp_server_disabled", "Enable the MCP server first.")
    # End the read transaction before any network I/O.
    db.commit()
    return server


def save_failure(db: Session, server: McpServer, error: McpError) -> None:
    record_failure(server, error)
    db.commit()


def check_connection(
    db: Session, organization_id: UUID, server_id: UUID, client: McpClient
) -> McpConnectionTest:
    server = usable_server(db, organization_id, server_id)
    try:
        probe = client.probe(server.url)
    except McpError as error:
        save_failure(db, server, error)
        return McpConnectionTest(
            status="unavailable",
            server=None,
            version=None,
            protocol_version=None,
            duration_ms=0,
            error=McpConnectionError(code=error.code, message=error.message),
        )
    record_reachable(server)
    db.commit()
    return McpConnectionTest(
        status="connected",
        server=probe.name,
        version=probe.version,
        protocol_version=probe.protocol_version,
        duration_ms=probe.duration_ms,
        error=None,
    )


def discover_tools(
    db: Session, organization_id: UUID, server_id: UUID, client: McpClient
) -> McpDiscoveryResponse:
    server = usable_server(db, organization_id, server_id)
    try:
        listing = client.list_tools(server.url)
    except McpError as error:
        save_failure(db, server, error)
        raise APIError(502, error.code, error.message) from error
    result = reconcile_tools(db, server, listing.tools)
    db.commit()
    return McpDiscoveryResponse(
        server=describe(db, server),
        tools=[tool_response(server, tool) for tool in result.tools],
        added=result.added,
        updated=result.updated,
        removed=result.removed,
    )


def list_tools(db: Session, organization_id: UUID, server_id: UUID) -> list[McpToolResponse]:
    server = get_server(db, organization_id, server_id)
    tools = db.scalars(
        select(McpTool)
        .where(McpTool.mcp_server_id == server.id, McpTool.organization_id == organization_id)
        .order_by(McpTool.is_available.desc(), McpTool.name)
    )
    return [tool_response(server, tool) for tool in tools]


def update_tool(
    db: Session, organization_id: UUID, server_id: UUID, tool_id: UUID, is_enabled: bool
) -> McpToolResponse:
    server = get_server(db, organization_id, server_id)
    tool = db.scalar(
        select(McpTool).where(
            McpTool.id == tool_id,
            McpTool.mcp_server_id == server.id,
            McpTool.organization_id == organization_id,
        )
    )
    if tool is None:
        raise APIError(404, "mcp_tool_not_found", "MCP tool not found.")
    tool.is_enabled = is_enabled
    db.commit()
    return tool_response(server, tool)
