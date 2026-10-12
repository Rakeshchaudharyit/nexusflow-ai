from collections.abc import Callable
from functools import cache
from time import perf_counter

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.agents import nodes
from app.agents.context import RunContext
from app.agents.state import AgentState

Node = Callable[[AgentState, Runtime[RunContext]], dict]

# State keys each node reads; recorded as the node_started payload.
NODE_INPUTS: dict[str, tuple[str, ...]] = {
    "analyze_request": ("user_input",),
    "create_plan": ("intent", "tool_source", "arguments"),
    "execute_demo_tool": ("plan",),
    "compose_response": ("intent", "tool_results"),
}


def elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def instrumented(name: str, node: Node) -> Node:
    """Report node lifecycle to the run's recorder so nodes stay free of persistence code."""
    keys = NODE_INPUTS[name]

    def run(state: AgentState, runtime: Runtime[RunContext]) -> dict:
        recorder = runtime.context.recorder
        recorder.node_started(name, {key: state[key] for key in keys if key in state})
        started = perf_counter()
        try:
            update = node(state, runtime)
        except Exception as error:
            recorder.node_failed(name, error, elapsed_ms(started))
            raise
        recorder.node_completed(name, update, elapsed_ms(started))
        return update

    return run


def build_agent_graph() -> StateGraph:
    graph = StateGraph(AgentState, context_schema=RunContext)
    for name in NODE_INPUTS:
        graph.add_node(name, instrumented(name, getattr(nodes, name)))
    graph.add_edge(START, "analyze_request")
    graph.add_edge("analyze_request", "create_plan")
    graph.add_conditional_edges(
        "create_plan", nodes.route_after_plan, ["execute_demo_tool", "compose_response"]
    )
    graph.add_edge("execute_demo_tool", "compose_response")
    graph.add_edge("compose_response", END)
    return graph


@cache
def compiled_agent_graph() -> CompiledStateGraph:
    # Compiled without a checkpointer: the graph holds no per-run data and is safe to share.
    return build_agent_graph().compile(name="nexusflow_demo_agent")
