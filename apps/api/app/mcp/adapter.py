"""Expose an organization's MCP tools through the agent runtime's ToolProvider contract."""

from collections.abc import Mapping
from typing import Any

from pydantic_core import to_jsonable_python
from sqlalchemy.orm import Session, sessionmaker

from app.agents.errors import ToolExecutionError
from app.agents.tools import ToolExecutionContext, ToolResult
from app.mcp.client import McpClient
from app.mcp.errors import (
    McpError,
    McpMalformedResult,
    McpServerDisabled,
    McpToolDisabled,
    McpToolNotFound,
)
from app.mcp.registry import (
    first_executable,
    parse_tool_key,
    record_failure,
    record_reachable,
    server_tools,
)
from app.mcp.schemas import schema_errors
from app.models.mcp import McpServer, McpTool


class McpToolProvider:
    """Resolves and calls MCP tools for exactly one organization.

    The organization comes from the server-created execution context. Tool keys from plans are
    looked up inside that organization only, so a key naming another tenant's server resolves
    to nothing. Persisted metadata gates the call (enabled, available, argument schema), and
    the live server is consulted on every call.
    """

    def __init__(
        self, sessions: sessionmaker[Session], client: McpClient, context: ToolExecutionContext
    ):
        self._sessions = sessions
        self._client = client
        self._organization_id = context.organization_id

    def find(self, tool_name: str) -> str | None:
        with self._sessions() as db:
            return first_executable(db, self._organization_id, tool_name)

    def _load(self, slug: str, name: str) -> tuple[McpServer, McpTool] | None:
        with self._sessions() as db:
            row = db.execute(
                server_tools(self._organization_id).where(
                    McpServer.slug == slug, McpTool.name == name
                )
            ).first()
            return (row.McpServer, row.McpTool) if row else None

    def _record(self, server_id, error: McpError | None) -> None:
        with self._sessions() as db:
            server = db.get(McpServer, server_id, with_for_update=True)
            if server is None or server.organization_id != self._organization_id:
                return
            if error is None:
                record_reachable(server)
            else:
                record_failure(server, error)
            db.commit()

    def execute(
        self, key: str, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult:
        if context.organization_id != self._organization_id:
            raise ToolExecutionError(
                "Tool execution context does not match this workspace.",
                code="tool_context_mismatch",
            )
        parsed = parse_tool_key(key)
        found = self._load(*parsed) if parsed else None
        if found is None:
            raise McpToolNotFound(details={"tool_type": "mcp", "tool_key": key})
        server, tool = found
        details = {
            "tool_type": "mcp",
            "tool_key": key,
            "tool_name": tool.name,
            "server_id": str(server.id),
            "server_name": server.name,
        }
        if not server.is_enabled:
            raise McpServerDisabled(details=details)
        if not tool.is_available:
            raise McpToolNotFound(details=details)
        if not tool.is_enabled:
            raise McpToolDisabled(details=details)
        invalid = schema_errors(tool.input_schema, dict(arguments))
        if invalid:
            raise ToolExecutionError(
                f"MCP tool '{tool.name}' received invalid arguments ({', '.join(invalid)}).",
                code="invalid_tool_arguments",
                details=details,
            )
        try:
            outcome = self._client.call_tool(server.url, tool.name, dict(arguments))
        except McpError as error:
            error.details = details
            self._record(server.id, error)
            raise
        self._record(server.id, None)
        if tool.output_schema and schema_errors(tool.output_schema, outcome.output):
            raise McpMalformedResult(details=details)
        return ToolResult(
            tool=tool.name,
            tool_key=key,
            tool_type="mcp",
            output=to_jsonable_python(outcome.output),
            metadata={
                "server_id": str(server.id),
                "server_name": server.name,
                "duration_ms": outcome.duration_ms,
            },
        )
