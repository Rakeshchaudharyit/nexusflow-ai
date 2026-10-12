from dataclasses import dataclass
from typing import Any, Protocol

from app.agents.providers import LLMProvider
from app.agents.tools import ToolExecutionContext, ToolResolver
from app.memory.context import MemoryContext


class ExecutionRecorder(Protocol):
    """Receives node lifecycle callbacks. The runtime's implementation persists them."""

    def node_started(self, node: str, payload: dict[str, Any]) -> None: ...

    def node_completed(self, node: str, payload: dict[str, Any], duration_ms: int) -> None: ...

    def node_failed(self, node: str, error: BaseException, duration_ms: int) -> None: ...


@dataclass(frozen=True)
class RunContext:
    """Per-run dependencies passed to LangGraph as `context`, separate from graph state.

    Nothing here is writable by nodes, and none of it is persisted in the state snapshot.
    """

    execution: ToolExecutionContext
    tools: ToolResolver
    llm: LLMProvider
    recorder: ExecutionRecorder
    # M8: selected, budgeted memory for this run. Read-only data, never authority.
    memory: MemoryContext | None = None
