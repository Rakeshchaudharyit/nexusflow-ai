"""Runtime tests that exercise LangGraph, tools and providers without HTTP or a database."""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.agents.context import RunContext
from app.agents.errors import ToolExecutionError
from app.agents.graph import compiled_agent_graph
from app.agents.intents import classify_request
from app.agents.providers import DeterministicLLMProvider
from app.agents.recorder import RunJob
from app.agents.runtime import initial_state
from app.agents.state import RunStateSnapshot
from app.agents.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolResolver,
    build_demo_registry,
)
from app.agents.tools.calculator import CalculatorInput, CalculatorTool
from app.schemas.health import ReadinessResponse, ServiceStatus


def ready_probe():
    return ReadinessResponse(status="ready", services=ServiceStatus(postgres="ok", redis="ok"))


class MemoryRecorder:
    def __init__(self):
        self.events: list[tuple[str, str]] = []

    def node_started(self, node, payload):
        self.events.append(("started", node))

    def node_completed(self, node, payload, duration_ms):
        assert duration_ms >= 0
        self.events.append(("completed", node))

    def node_failed(self, node, error, duration_ms):
        self.events.append(("failed", node))


def execution_context():
    return ToolExecutionContext(organization_id=uuid4(), user_id=uuid4(), run_id=uuid4())


def run_graph(text, registry=None):
    execution = execution_context()
    job = RunJob(
        run_id=execution.run_id,
        organization_id=execution.organization_id,
        agent_id=uuid4(),
        user_id=execution.user_id,
        input_text=text,
        instructions="Help operators.",
    )
    recorder = MemoryRecorder()
    context = RunContext(
        execution=execution,
        tools=ToolResolver(registry or build_demo_registry(ready_probe)),
        llm=DeterministicLLMProvider(),
        recorder=recorder,
    )
    state = compiled_agent_graph().invoke(initial_state(job), context=context)
    return state, recorder


@pytest.mark.parametrize(
    "text,intent,arguments",
    [
        (
            "Look up Acme Corporation and summarize the account.",
            "customer_lookup",
            {"query": "Acme Corporation"},
        ),
        ("find customer Globex and report", "customer_lookup", {"query": "Globex"}),
        (
            "What is 125 multiplied by 24?",
            "calculation",
            {"operation": "multiply", "left": "125", "right": "24"},
        ),
        ("12.5 / 5", "calculation", {"operation": "divide", "left": "12.5", "right": "5"}),
        ("7 minus -3", "calculation", {"operation": "subtract", "left": "7", "right": "-3"}),
        ("Add 2 plus 3.", "calculation", {"operation": "add", "left": "2", "right": "3"}),
        (
            "Look up run 3d91e951-cf9a-4557-88df-488ed63448a3",
            "customer_lookup",
            {"query": "run 3d91e951-cf9a-4557-88df-488ed63448a3"},
        ),
        ("Order SKU-12-34 status", "general", {}),
        ("Check platform system status.", "system_status", {}),
        ("Is the infrastructure healthy?", "system_status", {}),
        ("Hello there", "general", {}),
    ],
)
def test_deterministic_intent_classification(text, intent, arguments):
    result = classify_request(text)
    assert result.intent == intent
    assert result.arguments == arguments


def test_graph_executes_expected_node_sequence_for_tool_intent():
    state, recorder = run_graph("Look up Acme Corporation and summarize the account.")
    nodes = ["analyze_request", "create_plan", "execute_demo_tool", "compose_response"]
    assert recorder.events == [
        (phase, node) for node in nodes for phase in ("started", "completed")
    ]
    assert state["intent"] == "customer_lookup"
    assert state["plan"] == [
        {
            "step": 1,
            "action": "call_tool",
            "tool": "customer_lookup",
            "tool_key": "internal:customer_lookup",
            "arguments": {"query": "Acme Corporation"},
        },
        {"step": 2, "action": "compose_response"},
    ]
    assert state["tool_results"][0]["output"]["customer"]["account_owner"] == "Maya Chen"
    assert state["final_output"]["tools_used"] == ["internal:customer_lookup"]
    assert state["tool_results"][0]["tool_type"] == "internal"
    assert state["final_output"]["provider"] == "deterministic"
    assert state["final_output"]["summary"] == (
        "Acme Corporation: Enterprise segment, North America, status active, "
        "account owner Maya Chen. Source: demonstration data, not a CRM."
    )
    assert state["current_step"] == "compose_response"


def test_general_requests_skip_tool_node():
    state, recorder = run_graph("Hello there")
    assert [node for phase, node in recorder.events if phase == "completed"] == [
        "analyze_request",
        "create_plan",
        "compose_response",
    ]
    assert state["final_output"]["tools_used"] == []
    assert state["plan"] == [{"step": 1, "action": "compose_response"}]


def test_graph_records_failed_node_and_propagates_tool_error():
    with pytest.raises(ToolExecutionError) as error:
        run_graph("What is 4 divided by 0?")
    assert error.value.code == "division_by_zero"


def test_failed_node_is_reported_to_recorder():
    execution = execution_context()
    recorder = MemoryRecorder()
    context = RunContext(
        execution=execution,
        tools=ToolResolver(build_demo_registry(ready_probe)),
        llm=DeterministicLLMProvider(),
        recorder=recorder,
    )
    job = RunJob(execution.run_id, execution.organization_id, uuid4(), execution.user_id, "9/0", "")
    with pytest.raises(ToolExecutionError):
        compiled_agent_graph().invoke(initial_state(job), context=context)
    assert recorder.events[-1] == ("failed", "execute_demo_tool")


def test_calculation_and_status_responses_are_deterministic():
    state, _ = run_graph("What is 125 multiplied by 24?")
    assert state["tool_results"][0]["output"]["result"] == "3000"
    assert state["final_output"]["summary"] == "125 multiplied by 24 is 3000."
    state, _ = run_graph("Check platform system status.")
    assert state["final_output"]["summary"] == "Platform is ready: API ok, PostgreSQL ok, Redis ok."


@pytest.mark.parametrize(
    "operation,left,right,result",
    [
        ("add", "2", "3", "5"),
        ("subtract", "2", "3.5", "-1.5"),
        ("multiply", "125", "24", "3000"),
        ("divide", "1", "3", "0.3333333333"),
        ("divide", "10", "4", "2.5"),
    ],
)
def test_calculator_operations(operation, left, right, result):
    output = CalculatorTool().execute(
        CalculatorInput(operation=operation, left=Decimal(left), right=Decimal(right)),
        execution_context(),
    )
    assert output["result"] == result


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "power", "left": "2", "right": "3"},
        {"operation": "add", "left": "__import__('os').system('id')", "right": "1"},
        {"operation": "add", "left": "1e400", "right": "1"},
        {"operation": "add", "left": "NaN", "right": "1"},
        {"operation": "add", "left": "1", "right": "2", "expression": "1+2"},
    ],
)
def test_calculator_rejects_anything_but_two_bounded_numbers(arguments):
    registry = build_demo_registry(ready_probe)
    with pytest.raises(ToolExecutionError) as error:
        registry.execute("calculator", arguments, execution_context())
    assert error.value.code == "invalid_tool_arguments"


def test_registry_requires_server_created_context():
    registry = build_demo_registry(ready_probe)
    with pytest.raises(ToolExecutionError) as error:
        registry.execute("system_status", {}, None)
    assert error.value.code == "missing_execution_context"
    with pytest.raises(ToolExecutionError) as error:
        registry.execute("system_status", {}, {"organization_id": str(uuid4())})
    assert error.value.code == "missing_execution_context"
    with pytest.raises(TypeError):
        ToolExecutionContext(organization_id="not-a-uuid", user_id=uuid4(), run_id=uuid4())


def test_registry_rejects_unknown_and_duplicate_tools():
    registry = build_demo_registry(ready_probe)
    with pytest.raises(ToolExecutionError) as error:
        registry.execute("shell", {}, execution_context())
    assert error.value.code == "unknown_tool"
    with pytest.raises(ValueError):
        ToolRegistry([CalculatorTool(), CalculatorTool()])


def test_tool_definitions_expose_input_schemas():
    definitions = {item.name: item for item in build_demo_registry(ready_probe).definitions}
    assert set(definitions) == {"calculator", "customer_lookup", "system_status"}
    assert isinstance(definitions["calculator"], ToolDefinition)
    assert definitions["calculator"].input_schema()["required"] == ["operation", "left", "right"]


def test_customer_lookup_marks_demo_data_and_handles_unknown_customers():
    registry = build_demo_registry(ready_probe)
    found = registry.execute("customer_lookup", {"query": "northstar"}, execution_context())
    assert found.output["customer"]["company"] == "Northstar Labs"
    assert found.output["data_source"] == "demonstration"
    missing = registry.execute("customer_lookup", {"query": "Globex"}, execution_context())
    assert missing.output["found"] is False
    assert "Acme Corporation" in missing.output["available"]


def test_snapshot_is_allow_listed():
    state, _ = run_graph("What is 1 plus 1?")
    snapshot = RunStateSnapshot.from_state(state).model_dump(mode="json")
    assert "instructions" not in snapshot
    assert snapshot["input_text"] == "What is 1 plus 1?"
    assert snapshot["final_output"]["summary"] == "1 plus 1 is 2."


@pytest.mark.parametrize(
    "text,intent,source",
    [
        ("Use the MCP customer tool to look up Acme Corporation.", "customer_lookup", "mcp"),
        ("Use MCP to calculate 125 multiplied by 24.", "calculation", "mcp"),
        ("Ask mcp for the platform status", "system_status", "mcp"),
        ("Look up Acme Corporation and summarize the account.", "customer_lookup", "internal"),
        ("The MCP spec is interesting", "general", "internal"),
        ("Look up the MCPX account", "customer_lookup", "internal"),
    ],
)
def test_mcp_wording_selects_mcp_tool_source(text, intent, source):
    result = classify_request(text)
    assert (result.intent, result.tool_source) == (intent, source)


def test_mcp_plan_maps_arguments_to_mcp_schemas():
    from app.agents.nodes import TOOL_ROUTES

    tool, mapping = TOOL_ROUTES[("mcp", "calculation")]
    assert tool == "calculate"
    assert mapping({"operation": "multiply", "left": "125", "right": "2.5"}) == {
        "operation": "multiply",
        "a": 125,
        "b": 2.5,
    }
    assert TOOL_ROUTES[("mcp", "customer_lookup")][1]({"query": "Acme"}) == {"company": "Acme"}


def test_internal_and_mcp_demo_datasets_stay_aligned():
    from nexusflow_mcp_demo.data import DEMO_CUSTOMERS as MCP_CUSTOMERS

    from app.agents.tools.customers import DEMO_CUSTOMERS

    assert MCP_CUSTOMERS == DEMO_CUSTOMERS
