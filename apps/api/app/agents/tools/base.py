from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import to_jsonable_python

from app.agents.errors import ToolExecutionError


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Server-created identity for a single tool call.

    Built by the runtime from the persisted run, never from user input, agent instructions or
    graph state. Tools that touch tenant data must scope every access to `organization_id`.
    """

    organization_id: UUID
    user_id: UUID
    run_id: UUID
    # M9: knowledge sources this caller may search (tool + source grants, loaded at run start).
    knowledge_source_ids: tuple[UUID, ...] = ()

    def __post_init__(self):
        for field in ("organization_id", "user_id", "run_id"):
            if not isinstance(getattr(self, field), UUID):
                raise TypeError(f"ToolExecutionContext.{field} must be a UUID")
        if not all(isinstance(item, UUID) for item in self.knowledge_source_ids):
            raise TypeError("ToolExecutionContext.knowledge_source_ids must contain UUIDs")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]

    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()


ToolType = Literal["internal", "mcp"]


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    tool: str
    tool_key: str
    tool_type: ToolType = "internal"
    status: Literal["ok"] = "ok"
    output: dict[str, Any]
    # Safe call metadata such as MCP server id/name and duration; never credentials.
    metadata: dict[str, Any] = {}


class Tool(Protocol):
    definition: ToolDefinition

    def execute(self, arguments: Any, context: ToolExecutionContext) -> Mapping[str, Any]: ...


class ToolRegistry:
    """Resolves tools by name and enforces the call contract shared by every tool.

    Arguments are validated against the tool's input model, a valid execution context is
    mandatory, and outputs are converted to JSON-safe values before entering graph state.
    """

    def __init__(self, tools: Iterable[Tool]):
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            name = tool.definition.name
            if name in self._tools:
                raise ValueError(f"Duplicate tool name: {name}")
            self._tools[name] = tool

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    @property
    def definitions(self) -> list[ToolDefinition]:
        return [tool.definition for tool in self._tools.values()]

    def execute(
        self, name: str, arguments: Mapping[str, Any], context: ToolExecutionContext | None
    ) -> ToolResult:
        if not isinstance(context, ToolExecutionContext):
            raise ToolExecutionError(
                "Tool execution requires a server-created context.",
                code="missing_execution_context",
            )
        tool = self._tools.get(name)
        if tool is None:
            raise ToolExecutionError(f"Tool '{name}' is not available.", code="unknown_tool")
        try:
            parsed = tool.definition.input_model.model_validate(arguments)
        except ValidationError as error:
            raise ToolExecutionError(
                f"Tool '{name}' received invalid arguments.", code="invalid_tool_arguments"
            ) from error
        output = tool.execute(parsed, context)
        return ToolResult(
            tool=name, tool_key=f"internal:{name}", output=to_jsonable_python(dict(output))
        )
