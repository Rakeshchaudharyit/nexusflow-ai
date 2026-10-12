from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel

# memory_recall (M8): answered from thread/agent memory facts, with no tool call.
# knowledge_search (M9): answered from the agent's knowledge sources, with citations.
Intent = Literal[
    "general",
    "customer_lookup",
    "calculation",
    "system_status",
    "memory_recall",
    "knowledge_search",
]
ToolSource = Literal["internal", "mcp"]


class PlanStep(TypedDict):
    step: int
    action: Literal["call_tool", "compose_response"]
    tool: NotRequired[str]
    tool_key: NotRequired[str]
    arguments: NotRequired[dict[str, Any]]


class ToolCallRecord(TypedDict):
    step: int
    tool: str
    tool_key: str
    tool_type: ToolSource
    status: Literal["ok"]
    output: dict[str, Any]
    metadata: dict[str, Any]


class FinalOutput(TypedDict):
    intent: Intent
    summary: str
    tools_used: list[str]
    provider: str
    # M9: structured citations for every [K#] reference in the summary (and only those).
    citations: NotRequired[list[dict[str, Any]]]


class RunError(TypedDict):
    code: str
    message: str
    node: str | None
    details: NotRequired[dict[str, Any]]


class AgentState(TypedDict):
    """LangGraph channel schema. Every value must stay JSON-serializable.

    Identifiers are informational copies for the snapshot; tools never read them. Tool
    authorization uses the runtime's ToolExecutionContext instead.
    """

    run_id: str
    organization_id: str
    agent_id: str
    user_input: str
    instructions: str
    intent: NotRequired[Intent]
    tool_source: NotRequired[ToolSource]
    arguments: NotRequired[dict[str, Any]]
    plan: NotRequired[list[PlanStep]]
    tool_results: NotRequired[list[ToolCallRecord]]
    final_output: NotRequired[FinalOutput]
    errors: NotRequired[list[RunError]]
    current_step: NotRequired[str]


class RunStateSnapshot(BaseModel):
    """Allow-listed view of AgentState persisted on agent_runs.state_snapshot.

    Agent instructions and any non-listed keys are intentionally excluded.
    """

    run_id: str
    organization_id: str
    agent_id: str
    input_text: str
    intent: Intent | None = None
    plan: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    final_output: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = []
    current_step: str | None = None

    @classmethod
    def from_state(cls, state: AgentState, error: RunError | None = None) -> "RunStateSnapshot":
        errors = [*state.get("errors", []), *([error] if error else [])]
        return cls(
            run_id=state["run_id"],
            organization_id=state["organization_id"],
            agent_id=state["agent_id"],
            input_text=state["user_input"],
            intent=state.get("intent"),
            plan=state.get("plan", []),
            tool_results=state.get("tool_results", []),
            final_output=state.get("final_output"),
            errors=errors,
            current_step=state.get("current_step"),
        )
