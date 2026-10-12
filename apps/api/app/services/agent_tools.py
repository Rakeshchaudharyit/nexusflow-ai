"""Per-agent tool assignments: the permission foundation for team members.

A key is accepted only if it resolves to an internal tool or to a discovered MCP tool owned by
the caller's organization. MCP assignments also store the tool's row id, which the database ties
to the same organization.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents.tools import ToolRegistry
from app.core.errors import APIError
from app.mcp.registry import parse_tool_key, server_tools, tool_key
from app.models.mcp import McpServer, McpTool
from app.models.teams import AgentTool
from app.schemas.teams import AgentToolResponse, ToolCatalogEntry
from app.services.agents import get_agent


def assignment_response(assignment: AgentTool) -> AgentToolResponse:
    return AgentToolResponse(
        id=assignment.id,
        agent_id=assignment.agent_id,
        tool_key=assignment.tool_key,
        tool_type="mcp" if assignment.mcp_tool_id else "internal",
        is_enabled=assignment.is_enabled,
        created_at=assignment.created_at,
    )


def tool_catalog(
    db: Session, organization_id: UUID, internal: ToolRegistry
) -> list[ToolCatalogEntry]:
    entries = [
        ToolCatalogEntry(
            tool_key=f"internal:{definition.name}",
            tool_type="internal",
            name=definition.name,
            description=definition.description,
            is_enabled=True,
        )
        for definition in internal.definitions
    ]
    for server, tool in db.execute(
        server_tools(organization_id)
        .where(McpTool.is_available.is_(True))
        .order_by(McpServer.name, McpTool.name)
    ):
        entries.append(
            ToolCatalogEntry(
                tool_key=tool_key(server.slug, tool.name),
                tool_type="mcp",
                name=tool.name,
                description=tool.description,
                server_name=server.name,
                is_enabled=server.is_enabled and tool.is_enabled,
            )
        )
    return entries


def list_assignments(db: Session, organization_id: UUID, agent_ids: list[UUID]) -> list[AgentTool]:
    return list(
        db.scalars(
            select(AgentTool)
            .where(AgentTool.organization_id == organization_id, AgentTool.agent_id.in_(agent_ids))
            .order_by(AgentTool.created_at, AgentTool.tool_key)
        )
    )


def agent_tools(db: Session, organization_id: UUID, agent_id: UUID) -> list[AgentToolResponse]:
    agent = get_agent(db, organization_id, agent_id)
    return [assignment_response(item) for item in list_assignments(db, organization_id, [agent.id])]


def resolve_key(
    db: Session, organization_id: UUID, key: str, internal: ToolRegistry
) -> UUID | None:
    """Return the MCP tool id for an MCP key, None for an internal key; reject anything else."""
    invalid = APIError(422, "invalid_tool_key", "The tool key does not match an available tool.")
    source, _, name = key.partition(":")
    if source == "internal":
        if name not in internal:
            raise invalid
        return None
    parsed = parse_tool_key(key)
    if parsed is None:
        raise invalid
    slug, tool_name = parsed
    row = db.execute(
        server_tools(organization_id).where(
            McpServer.slug == slug, McpTool.name == tool_name, McpTool.is_available.is_(True)
        )
    ).first()
    if row is None:
        # Another organization's tool is indistinguishable from a missing one.
        raise invalid
    return row.McpTool.id


def assign_tool(
    db: Session, organization_id: UUID, agent_id: UUID, key: str, internal: ToolRegistry
) -> AgentToolResponse:
    agent = get_agent(db, organization_id, agent_id)
    assignment = AgentTool(
        organization_id=organization_id,
        agent_id=agent.id,
        tool_key=key,
        mcp_tool_id=resolve_key(db, organization_id, key, internal),
    )
    db.add(assignment)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise APIError(409, "tool_already_assigned", "This tool is already assigned.") from error
    return assignment_response(assignment)


def get_assignment(
    db: Session, organization_id: UUID, agent_id: UUID, assignment_id: UUID
) -> AgentTool:
    assignment = db.scalar(
        select(AgentTool).where(
            AgentTool.id == assignment_id,
            AgentTool.agent_id == agent_id,
            AgentTool.organization_id == organization_id,
        )
    )
    if assignment is None:
        raise APIError(404, "tool_assignment_not_found", "Tool assignment not found.")
    return assignment


def update_assignment(
    db: Session, organization_id: UUID, agent_id: UUID, assignment_id: UUID, is_enabled: bool
) -> AgentToolResponse:
    assignment = get_assignment(db, organization_id, agent_id, assignment_id)
    assignment.is_enabled = is_enabled
    db.commit()
    return assignment_response(assignment)


def remove_assignment(
    db: Session, organization_id: UUID, agent_id: UUID, assignment_id: UUID
) -> None:
    db.delete(get_assignment(db, organization_id, agent_id, assignment_id))
    db.commit()
