from collections.abc import Mapping
from typing import Any

from app.agents.errors import ToolExecutionError
from app.agents.tools import ToolExecutionContext, ToolResolver, ToolResult


class AgentToolbox:
    """The only way a team member reaches tools: its enabled assignments, nothing else.

    Assignments come from agent_tools rows loaded for the run's organization. Execution goes
    through the shared ToolResolver, so MCP calls use the M4 adapter unchanged.
    """

    def __init__(
        self, resolver: ToolResolver, allowed: tuple[str, ...], execution: ToolExecutionContext
    ):
        self._resolver = resolver
        self.allowed = allowed
        self._execution = execution

    @property
    def knowledge_sources(self) -> tuple:
        return self._execution.knowledge_source_ids

    def first_named(self, *names: str) -> str | None:
        """First assigned key (in assignment order) whose tool name is one of `names`."""
        return next((key for key in self.allowed if key.rsplit(":", 1)[-1] in names), None)

    def call(self, key: str, arguments: Mapping[str, Any]) -> ToolResult:
        if key not in self.allowed:
            raise ToolExecutionError(
                f"Tool '{key}' is not assigned to this agent.",
                code="tool_not_permitted",
                details={"tool_key": key},
            )
        return self._resolver.execute(key, arguments, self._execution)
