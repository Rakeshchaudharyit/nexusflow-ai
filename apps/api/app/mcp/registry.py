"""Tenant-scoped queries and connectivity bookkeeping for registered MCP servers."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.mcp.errors import McpError
from app.models.mcp import McpServer, McpServerStatus, McpTool

TOOL_KEY_PREFIX = "mcp"


def tool_key(server_slug: str, tool_name: str) -> str:
    return f"{TOOL_KEY_PREFIX}:{server_slug}:{tool_name}"


def parse_tool_key(key: str) -> tuple[str, str] | None:
    prefix, _, rest = key.partition(":")
    slug, _, name = rest.partition(":")
    return (slug, name) if prefix == TOOL_KEY_PREFIX and slug and name else None


def server_tools(organization_id: UUID) -> Select:
    """Tools joined to their server, constrained to one organization on both sides."""
    return (
        select(McpServer, McpTool)
        .join(
            McpTool,
            (McpTool.mcp_server_id == McpServer.id)
            & (McpTool.organization_id == McpServer.organization_id),
        )
        .where(McpServer.organization_id == organization_id)
    )


def first_executable(db: Session, organization_id: UUID, tool_name: str) -> str | None:
    """Key of the oldest enabled server offering an enabled, currently listed tool."""
    row = db.execute(
        server_tools(organization_id)
        .where(
            McpServer.is_enabled.is_(True),
            McpTool.name == tool_name,
            McpTool.is_enabled.is_(True),
            McpTool.is_available.is_(True),
        )
        .order_by(McpServer.created_at, McpServer.id)
        .limit(1)
    ).first()
    return tool_key(row.McpServer.slug, tool_name) if row else None


def record_reachable(server: McpServer) -> None:
    now = datetime.now(UTC)
    server.last_connected_at = now
    server.last_error_code = None
    server.last_error_message = None
    if server.is_enabled:
        server.status = McpServerStatus.CONNECTED


def record_failure(server: McpServer, error: McpError) -> None:
    """Connectivity failures mark the server unavailable; tool-level failures prove it is up."""
    if not error.connectivity:
        record_reachable(server)
        return
    server.last_error_code = error.code
    server.last_error_message = error.message[:500]
    if server.is_enabled:
        server.status = McpServerStatus.UNAVAILABLE
