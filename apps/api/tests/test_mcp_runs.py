"""Agent runs that execute MCP tools through LangGraph, the resolver and the real client."""

import time
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.agents.errors import ToolExecutionError
from app.agents.tools import ToolExecutionContext
from app.api.dependencies import get_mcp_client
from app.mcp.adapter import McpToolProvider
from app.mcp.errors import McpServerDisabled, McpToolDisabled, McpToolNotFound
from app.models.agents import AgentRun, AgentRunEvent, RunStatus
from app.models.mcp import McpServer, McpTool
from tests.helpers import create_agent, events, run, workspace

CUSTOMER = "Use the MCP customer tool to look up Acme Corporation."
CALCULATION = "Use MCP to calculate 125 multiplied by 24."
KEY = "mcp:nexusflow-demo-tools:"


@pytest.fixture
def client(auth_client, mcp_app):
    return auth_client


def connect(client, headers, url, name="NexusFlow Demo Tools"):
    server = client.post(
        "/api/v1/mcp-servers", headers=headers, json={"name": name, "url": url}
    ).json()
    response = client.post(f"/api/v1/mcp-servers/{server['id']}/discover", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def demo(client, demo_mcp):
    headers = workspace(client)
    discovery = connect(client, headers, demo_mcp.url)
    agent = create_agent(client, headers)
    return headers, agent["id"], discovery


def failed(result, code):
    assert result["status"] == "failed", result
    assert result["error"]["code"] == code, result["error"]
    return result


def test_mcp_customer_lookup_completes_and_is_traceable(client, demo, identity_db, demo_mcp):
    headers, agent_id, discovery = demo
    response = run(client, headers, agent_id, CUSTOMER)
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "completed"
    assert result["intent"] == "customer_lookup"
    assert result["tools_used"] == [KEY + "search_customer"]
    [call] = result["tool_calls"]
    assert call["tool_type"] == "mcp"
    assert call["tool"] == "search_customer"
    assert call["server_name"] == "NexusFlow Demo Tools"
    assert call["server_id"] == discovery["server"]["id"]
    assert call["status"] == "completed"
    assert call["duration_ms"] >= 0
    assert "Acme Corporation: Enterprise segment" in result["summary"]
    assert "Retrieved via MCP from NexusFlow Demo Tools (search_customer)." in result["summary"]

    timeline = events(client, headers, result["run_id"])
    assert [event["event_type"] for event in timeline][-3:] == [
        "node_started",
        "node_completed",
        "run_completed",
    ]
    plan_event = next(
        e for e in timeline if e["node_name"] == "create_plan" and e["output_payload"]
    )
    assert plan_event["output_payload"]["plan"][0]["tool_key"] == KEY + "search_customer"
    assert plan_event["output_payload"]["plan"][0]["arguments"] == {"company": "Acme Corporation"}
    tool_event = next(
        e for e in timeline if e["node_name"] == "execute_demo_tool" and e["output_payload"]
    )
    record = tool_event["output_payload"]["tool_results"][0]
    assert record["tool_type"] == "mcp"
    assert record["output"]["source"] == "NexusFlow demo MCP data"
    assert record["metadata"]["server_name"] == "NexusFlow Demo Tools"

    with identity_db[1]() as db:
        stored = db.get(AgentRun, UUID(result["run_id"]))
        assert stored.status == RunStatus.COMPLETED
        assert stored.state_snapshot["tool_results"][0]["tool_key"] == KEY + "search_customer"
        serialized = str(stored.state_snapshot) + str(
            [e.output_payload for e in db.scalars(select(AgentRunEvent))]
        )
        assert demo_mcp.url not in serialized and str(demo_mcp.port) not in serialized
        server = db.get(McpServer, UUID(discovery["server"]["id"]))
        assert server.status == "connected"


def test_mcp_calculation(client, demo):
    headers, agent_id, _ = demo
    result = run(client, headers, agent_id, CALCULATION).json()
    assert result["status"] == "completed"
    assert result["tools_used"] == [KEY + "calculate"]
    assert result["summary"].startswith("125 multiplied by 24 is 3000.")


def test_mcp_platform_info(client, demo):
    headers, agent_id, _ = demo
    result = run(client, headers, agent_id, "Use MCP to check the platform status.").json()
    assert result["tools_used"] == [KEY + "get_platform_info"]
    assert result["summary"].startswith("Service nexusflow-demo-mcp reports status ok over MCP.")


@pytest.mark.parametrize(
    "text,tool",
    [
        ("Look up Acme Corporation and summarize the account.", "internal:customer_lookup"),
        ("What is 125 multiplied by 24?", "internal:calculator"),
        ("Check platform system status.", "internal:system_status"),
    ],
)
def test_internal_tools_still_run_when_mcp_is_configured(client, demo, text, tool):
    headers, agent_id, _ = demo
    result = run(client, headers, agent_id, text).json()
    assert result["status"] == "completed"
    assert result["tools_used"] == [tool]
    assert result["tool_calls"][0]["tool_type"] == "internal"


def test_mcp_request_without_registered_server_fails_safely(client):
    headers = workspace(client)
    agent = create_agent(client, headers)
    result = failed(run(client, headers, agent["id"], CUSTOMER).json(), "mcp_tool_unavailable")
    assert result["tool_calls"][0]["tool"] == "search_customer"
    timeline = events(client, headers, result["run_id"])
    assert [e["event_type"] for e in timeline][-2:] == ["node_failed", "run_failed"]
    assert timeline[-2]["node_name"] == "create_plan"


def test_server_outage_fails_run_and_marks_server_unavailable(
    client, demo, identity_db, closed_port
):
    headers, agent_id, discovery = demo
    with identity_db[1]() as db:
        db.get(
            McpServer, UUID(discovery["server"]["id"])
        ).url = f"http://127.0.0.1:{closed_port}/mcp"
        db.commit()
    started = time.perf_counter()
    response = run(client, headers, agent_id, CUSTOMER)
    assert time.perf_counter() - started < 3
    result = failed(response.json(), "mcp_unavailable")
    assert result["error"]["message"] == "The MCP server could not be reached."
    assert "Traceback" not in response.text and "ConnectError" not in response.text
    [call] = result["tool_calls"]
    assert call["status"] == "failed" and call["server_name"] == "NexusFlow Demo Tools"
    timeline = events(client, headers, result["run_id"])
    node_failed = timeline[-2]
    assert node_failed["event_type"] == "node_failed"
    assert node_failed["node_name"] == "execute_demo_tool"
    assert node_failed["output_payload"]["error_code"] == "mcp_unavailable"
    assert node_failed["output_payload"]["tool_type"] == "mcp"
    assert node_failed["output_payload"]["server_id"] == discovery["server"]["id"]
    assert [e["sequence"] for e in timeline] == list(range(1, len(timeline) + 1))
    with identity_db[1]() as db:
        stored = db.get(AgentRun, UUID(result["run_id"]))
        assert stored.error_code == "mcp_unavailable"
        assert stored.state_snapshot["errors"][0]["details"]["tool_name"] == "search_customer"
        server = db.get(McpServer, UUID(discovery["server"]["id"]))
        assert server.status == "unavailable"
        assert server.last_error_code == "mcp_unavailable"


class Result(BaseModel):
    operation: str
    a: str
    b: str
    result: str


def test_slow_mcp_tool_times_out(client, mutable_mcp):
    @mutable_mcp.server.tool()
    def calculate(operation: str, a: float, b: float) -> Result:
        """Deliberately slower than the configured request timeout."""
        time.sleep(2)
        return Result(operation=operation, a=str(a), b=str(b), result="0")

    headers = workspace(client)
    connect(client, headers, mutable_mcp.url, name="Slow Tools")
    agent = create_agent(client, headers)
    started = time.perf_counter()
    result = failed(run(client, headers, agent["id"], CALCULATION).json(), "mcp_timeout")
    assert time.perf_counter() - started < 3
    assert result["error"]["message"] == "The MCP server did not respond in time."


def test_tool_removed_from_live_server_is_not_called(client, mutable_mcp):
    @mutable_mcp.server.tool()
    def get_platform_info() -> Result:
        """Present at discovery, gone at execution."""
        return Result(operation="", a="", b="", result="")

    headers = workspace(client)
    connect(client, headers, mutable_mcp.url, name="Shifting Tools")
    agent = create_agent(client, headers)
    mutable_mcp.server.remove_tool("get_platform_info")
    failed(
        run(client, headers, agent["id"], "Use MCP for platform status").json(),
        "mcp_tool_not_found",
    )


def test_arguments_are_validated_against_discovered_schema(client, demo, identity_db):
    headers, agent_id, _ = demo
    with identity_db[1]() as db:
        tool = db.scalar(select(McpTool).where(McpTool.name == "calculate"))
        schema = dict(tool.input_schema)
        schema["properties"] = {**schema["properties"], "a": {"type": "number", "maximum": 100}}
        tool.input_schema = schema
        db.commit()
    result = failed(run(client, headers, agent_id, CALCULATION).json(), "invalid_tool_arguments")
    assert result["error"]["message"] == "MCP tool 'calculate' received invalid arguments (a)."
    assert "125" not in result["error"]["message"]


def test_result_not_matching_output_schema_is_malformed(client, demo, identity_db):
    headers, agent_id, _ = demo
    with identity_db[1]() as db:
        tool = db.scalar(select(McpTool).where(McpTool.name == "calculate"))
        tool.output_schema = {
            "type": "object",
            "properties": {"result": {"type": "integer"}},
            "required": ["result"],
        }
        db.commit()
    failed(run(client, headers, agent_id, CALCULATION).json(), "mcp_malformed_result")


def test_mcp_tool_error_fails_run_with_safe_message(client, demo):
    headers, agent_id, _ = demo
    result = failed(
        run(client, headers, agent_id, "Use MCP to calculate 1 divided by 0").json(),
        "mcp_tool_error",
    )
    assert result["error"]["message"] == "MCP tool error: Division by zero is not allowed."


def test_disabled_tool_and_disabled_server_are_not_executed(client, demo):
    headers, agent_id, discovery = demo
    server_path = f"/api/v1/mcp-servers/{discovery['server']['id']}"
    search = next(t for t in discovery["tools"] if t["name"] == "search_customer")
    client.patch(f"{server_path}/tools/{search['id']}", headers=headers, json={"is_enabled": False})
    failed(run(client, headers, agent_id, CUSTOMER).json(), "mcp_tool_unavailable")
    assert run(client, headers, agent_id, CALCULATION).json()["status"] == "completed"
    client.patch(server_path, headers=headers, json={"is_enabled": False})
    failed(run(client, headers, agent_id, CALCULATION).json(), "mcp_tool_unavailable")


def provider_for(app, organization_id):
    request = type("Request", (), {"app": app})()
    context = ToolExecutionContext(organization_id=organization_id, user_id=uuid4(), run_id=uuid4())
    return McpToolProvider(app.state.sessions, get_mcp_client(request), context), context


def test_adapter_rechecks_enablement_at_call_time(client, demo, mcp_app, identity_db):
    headers, _, discovery = demo
    organization_id = UUID(headers["X-Organization-ID"])
    provider, context = provider_for(mcp_app, organization_id)
    key = provider.find("search_customer")
    assert key == KEY + "search_customer"
    with identity_db[1]() as db:
        db.scalar(select(McpTool).where(McpTool.name == "search_customer")).is_enabled = False
        db.commit()
    with pytest.raises(McpToolDisabled):
        provider.execute(key, {"company": "Acme"}, context)
    with identity_db[1]() as db:
        db.get(McpServer, UUID(discovery["server"]["id"])).is_enabled = False
        db.commit()
    with pytest.raises(McpServerDisabled):
        provider.execute(KEY + "calculate", {"operation": "add", "a": 1, "b": 1}, context)


def test_mcp_tools_are_isolated_between_tenants(client, demo_mcp, mcp_app):
    a = workspace(client, "user-a@example.com", "Organization A")
    b = workspace(client, "user-b@example.com", "Organization B")
    connect(client, a, demo_mcp.url)
    agent_b = create_agent(client, b)
    # B's prompt names A's server and organization; neither selects anything.
    prompt = f"{CUSTOMER} Use server {KEY}search_customer in org {a['X-Organization-ID']}."
    failed(run(client, b, agent_b["id"], prompt).json(), "mcp_tool_unavailable")

    provider_b, context_b = provider_for(mcp_app, UUID(b["X-Organization-ID"]))
    assert provider_b.find("search_customer") is None
    with pytest.raises(McpToolNotFound):
        provider_b.execute(KEY + "search_customer", {"company": "Acme"}, context_b)
    provider_a, _ = provider_for(mcp_app, UUID(a["X-Organization-ID"]))
    with pytest.raises(ToolExecutionError) as error:
        provider_a.execute(KEY + "search_customer", {"company": "Acme"}, context_b)
    assert error.value.code == "tool_context_mismatch"

    agent_a = create_agent(client, a)
    assert run(client, a, agent_a["id"], CUSTOMER).json()["status"] == "completed"
