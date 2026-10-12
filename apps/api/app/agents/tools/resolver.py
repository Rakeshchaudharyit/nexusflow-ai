from collections.abc import Mapping
from typing import Any, Protocol

from app.agents.errors import ToolExecutionError
from app.agents.tools.base import ToolExecutionContext, ToolRegistry, ToolResult

INTERNAL = "internal"


class ToolProvider(Protocol):
    """An external tool source, such as MCP, behind the same call contract as internal tools."""

    def find(self, tool_name: str) -> str | None:
        """Return the stable key of an executable tool with this name, or None."""

    def execute(
        self, key: str, arguments: Mapping[str, Any], context: ToolExecutionContext
    ) -> ToolResult: ...


class ToolResolver:
    """Routes namespaced tool keys to internal tools or a provider.

    Keys are `internal:<tool>` or `<source>:...` (e.g. `mcp:<server-slug>:<tool>`). Graph nodes
    only see keys and ToolResults; protocol details stay inside providers.
    """

    def __init__(self, internal: ToolRegistry, providers: Mapping[str, ToolProvider] | None = None):
        self._internal = internal
        self._providers = dict(providers or {})

    def resolve(self, source: str, tool_name: str) -> str | None:
        if source == INTERNAL:
            return f"{INTERNAL}:{tool_name}" if tool_name in self._internal else None
        provider = self._providers.get(source)
        return provider.find(tool_name) if provider else None

    def execute(
        self, key: str, arguments: Mapping[str, Any], context: ToolExecutionContext | None
    ) -> ToolResult:
        source, _, name = key.partition(":")
        if source == INTERNAL:
            return self._internal.execute(name, arguments, context)
        provider = self._providers.get(source)
        if provider is None or not name:
            raise ToolExecutionError(f"Tool '{key}' is not available.", code="unknown_tool")
        if not isinstance(context, ToolExecutionContext):
            raise ToolExecutionError(
                "Tool execution requires a server-created context.",
                code="missing_execution_context",
            )
        return provider.execute(key, arguments, context)
