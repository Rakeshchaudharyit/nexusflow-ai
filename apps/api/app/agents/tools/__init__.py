from collections.abc import Callable

from app.agents.tools.base import (
    Tool,
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolResult,
)
from app.agents.tools.calculator import CalculatorTool
from app.agents.tools.customers import CustomerLookupTool
from app.agents.tools.resolver import INTERNAL, ToolProvider, ToolResolver
from app.agents.tools.system_status import SystemStatusTool
from app.schemas.health import ReadinessResponse


def build_demo_registry(
    status_probe: Callable[[], ReadinessResponse], extra: tuple[Tool, ...] = ()
) -> ToolRegistry:
    """Local, deterministic tools. This is an in-process registry, not an MCP server.
    `extra` adds tools that need runtime collaborators (M9: knowledge_search)."""
    return ToolRegistry(
        [CalculatorTool(), CustomerLookupTool(), SystemStatusTool(status_probe), *extra]
    )


__all__ = [
    "INTERNAL",
    "ToolProvider",
    "ToolResolver",
    "Tool",
    "ToolDefinition",
    "ToolExecutionContext",
    "ToolRegistry",
    "ToolResult",
    "build_demo_registry",
]
