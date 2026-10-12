"""Reconcile a live tools/list response with persisted tool metadata.

- New tools are inserted enabled and available.
- Known tools get description and schemas refreshed and become available again; an operator's
  enable/disable choice is preserved.
- Tools the server no longer lists are kept for audit but marked unavailable, which makes them
  non-executable until a later discovery lists them again.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.mcp.client import RemoteTool
from app.mcp.registry import record_reachable
from app.mcp.schemas import normalize_tools
from app.models.mcp import McpServer, McpTool


@dataclass
class DiscoveryResult:
    tools: list[McpTool]
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def reconcile_tools(db: Session, server: McpServer, remote: list[RemoteTool]) -> DiscoveryResult:
    now = datetime.now(UTC)
    existing = {
        tool.name: tool
        for tool in db.scalars(
            select(McpTool).where(
                McpTool.mcp_server_id == server.id,
                McpTool.organization_id == server.organization_id,
            )
        )
    }
    result = DiscoveryResult(tools=[])
    seen = set()
    for item in normalize_tools(remote):
        seen.add(item.name)
        tool = existing.get(item.name)
        if tool is None:
            tool = McpTool(
                organization_id=server.organization_id,
                mcp_server_id=server.id,
                name=item.name,
                description=item.description or "",
                input_schema=item.input_schema,
                output_schema=item.output_schema,
                discovered_at=now,
            )
            db.add(tool)
            result.added.append(item.name)
        else:
            changed = (
                tool.description != (item.description or "")
                or tool.input_schema != item.input_schema
                or tool.output_schema != item.output_schema
                or not tool.is_available
            )
            tool.description = item.description or ""
            tool.input_schema = item.input_schema
            tool.output_schema = item.output_schema
            tool.is_available = True
            tool.discovered_at = now
            if changed:
                result.updated.append(item.name)
        result.tools.append(tool)
    for name, tool in existing.items():
        if name not in seen and tool.is_available:
            tool.is_available = False
            result.removed.append(name)
    server.last_discovered_at = now
    record_reachable(server)
    return result
