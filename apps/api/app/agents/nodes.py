"""Graph nodes. Each returns a partial state update and performs no persistence.

Nodes refer to tools only by (source, name) and resolved keys; MCP protocol details live in
the tool provider behind `runtime.context.tools`.
"""

import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from langgraph.runtime import Runtime

from app.agents.context import RunContext
from app.agents.errors import ToolExecutionError
from app.agents.intents import (
    Classification,
    classify_request,
    recalls_memory,
    wants_knowledge,
)
from app.agents.providers import GenerationRequest
from app.agents.state import AgentState, FinalOutput, PlanStep, ToolCallRecord


def as_number(value: str) -> int | float:
    number = Decimal(value)
    return int(number) if number == number.to_integral_value() else float(number)


Arguments = dict[str, Any]
# Deterministic (source, intent) -> (tool name, argument mapping). No autonomous selection.
TOOL_ROUTES: dict[tuple[str, str], tuple[str, Callable[[Arguments], Arguments]]] = {
    ("internal", "customer_lookup"): ("customer_lookup", dict),
    ("internal", "calculation"): ("calculator", dict),
    ("internal", "system_status"): ("system_status", dict),
    ("internal", "knowledge_search"): ("knowledge_search", dict),
    ("mcp", "customer_lookup"): ("search_customer", lambda args: {"company": args["query"]}),
    (
        "mcp",
        "calculation",
    ): (
        "calculate",
        lambda args: {
            "operation": args["operation"],
            "a": as_number(args["left"]),
            "b": as_number(args["right"]),
        },
    ),
    ("mcp", "system_status"): ("get_platform_info", lambda args: {}),
}


def analyze_request(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    classification = classify_request(state["user_input"])
    memory = runtime.context.memory
    if runtime.context.execution.knowledge_source_ids and wants_knowledge(
        state["user_input"], classification
    ):
        # Server-side grant (tool + sources), not the text, decides that knowledge is usable.
        classification = Classification("knowledge_search", {"query": state["user_input"][:500]})
    elif memory is not None and recalls_memory(
        state["user_input"], classification, bool(memory.account())
    ):
        classification = Classification("memory_recall", {})
    return {
        "intent": classification.intent,
        "tool_source": classification.tool_source,
        "arguments": classification.arguments,
        "current_step": "analyze_request",
    }


def create_plan(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    plan: list[PlanStep] = []
    source = state.get("tool_source", "internal")
    route = TOOL_ROUTES.get((source, state["intent"]))
    if route:
        tool, map_arguments = route
        key = runtime.context.tools.resolve(source, tool)
        if key is None:
            raise ToolExecutionError(
                f"No enabled {source} tool named '{tool}' is available in this workspace.",
                code=f"{source}_tool_unavailable",
                details={"tool_type": source, "tool_name": tool},
            )
        plan.append(
            {
                "step": 1,
                "action": "call_tool",
                "tool": tool,
                "tool_key": key,
                "arguments": map_arguments(state["arguments"]),
            }
        )
    plan.append({"step": len(plan) + 1, "action": "compose_response"})
    return {"plan": plan, "current_step": "create_plan"}


def route_after_plan(state: AgentState) -> str:
    if any(step["action"] == "call_tool" for step in state["plan"]):
        return "execute_demo_tool"
    return "compose_response"


def execute_demo_tool(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    results: list[ToolCallRecord] = []
    for step in state["plan"]:
        if step["action"] != "call_tool":
            continue
        result = runtime.context.tools.execute(
            step["tool_key"], step.get("arguments", {}), runtime.context.execution
        )
        results.append(
            {
                "step": step["step"],
                "tool": result.tool,
                "tool_key": result.tool_key,
                "tool_type": result.tool_type,
                "status": result.status,
                "output": result.output,
                "metadata": result.metadata,
            }
        )
    return {"tool_results": results, "current_step": "execute_demo_tool"}


CITATION = re.compile(r"\[(K\d+)\]")


def cited(summary: str, tool_results: list[ToolCallRecord]) -> list[dict[str, Any]]:
    """Structured citations for the [K#] ids the answer actually uses, taken from the
    retrieval results; an id that matches no retrieved chunk is never emitted."""
    retrieved = {
        result["citation_id"]: result
        for record in tool_results
        if record["tool"] == "knowledge_search"
        for result in record["output"].get("results", [])
    }
    used = dict.fromkeys(CITATION.findall(summary))
    return [
        {key: value for key, value in retrieved[cid].items() if "_score" not in key}
        for cid in used
        if cid in retrieved
    ]


def compose_response(state: AgentState, runtime: Runtime[RunContext]) -> dict:
    tool_results = state.get("tool_results", [])
    llm = runtime.context.llm
    summary = llm.generate(
        GenerationRequest(
            instructions=state["instructions"],
            user_input=state["user_input"],
            intent=state["intent"],
            tool_results=tool_results,
            memory=runtime.context.memory,
        )
    )
    output: FinalOutput = {
        "intent": state["intent"],
        "summary": summary,
        "tools_used": [record["tool_key"] for record in tool_results],
        "provider": llm.name,
    }
    if state["intent"] == "knowledge_search":
        output["citations"] = cited(summary, tool_results)
    return {"final_output": output, "current_step": "compose_response"}
