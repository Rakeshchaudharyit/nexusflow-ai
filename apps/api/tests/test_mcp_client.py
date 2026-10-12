"""McpClient against real MCP servers over streamable HTTP, plus failure classification."""

from time import perf_counter

import httpx2
import pytest
from mcp.shared.exceptions import MCPError

from app.mcp.client import McpClient, McpTimeouts, classify
from app.mcp.errors import (
    McpProtocolError,
    McpTimeout,
    McpToolFailed,
    McpToolNotFound,
    McpUnavailable,
    McpUrlRejected,
)
from app.mcp.urls import UrlPolicy


@pytest.fixture
def client(mcp_settings):
    return McpClient(
        UrlPolicy(allowed_hosts=frozenset(mcp_settings["mcp_allowed_hosts"])),
        McpTimeouts(connect_seconds=0.5, request_seconds=0.75),
    )


def test_probe_reports_server_identity_and_protocol(client, demo_mcp):
    probe = client.probe(demo_mcp.url)
    assert probe.name == "nexusflow-demo-mcp"
    assert probe.version == "0.4.0"
    assert probe.protocol_version
    assert probe.duration_ms >= 0


def test_list_tools_returns_live_schemas(client, demo_mcp):
    listing = client.list_tools(demo_mcp.url)
    tools = {tool.name: tool for tool in listing.tools}
    assert set(tools) == {"search_customer", "calculate", "get_platform_info"}
    assert tools["calculate"].input_schema["properties"]["operation"]["enum"] == [
        "add",
        "subtract",
        "multiply",
        "divide",
    ]
    assert tools["search_customer"].output_schema["type"] == "object"
    assert listing.server.name == "nexusflow-demo-mcp"


def test_call_tool_returns_structured_content(client, demo_mcp):
    outcome = client.call_tool(
        demo_mcp.url, "calculate", {"operation": "multiply", "a": 125, "b": 24}
    )
    assert outcome.output == {"operation": "multiply", "a": "125", "b": "24", "result": "3000"}
    customer = client.call_tool(demo_mcp.url, "search_customer", {"company": "Acme"}).output
    assert customer["company"] == "Acme Corporation"
    assert customer["source"] == "NexusFlow demo MCP data"


def test_tool_error_is_reported_safely(client, demo_mcp):
    with pytest.raises(McpToolFailed) as error:
        client.call_tool(demo_mcp.url, "calculate", {"operation": "divide", "a": 1, "b": 0})
    assert error.value.message == "MCP tool error: Division by zero is not allowed."
    assert error.value.connectivity is False


def test_tool_missing_on_live_server(client, demo_mcp):
    with pytest.raises(McpToolNotFound):
        client.call_tool(demo_mcp.url, "run_shell", {"command": "id"})


def test_unreachable_server(client, closed_port):
    with pytest.raises(McpUnavailable) as error:
        client.probe(f"http://127.0.0.1:{closed_port}/mcp")
    assert error.value.connectivity is True


def test_slow_tool_hits_bounded_timeout(client, mutable_mcp):
    started = perf_counter()
    with pytest.raises(McpTimeout):
        client.call_tool(mutable_mcp.url, "slow", {})
    assert perf_counter() - started < 1.6


def test_wrong_path_is_a_protocol_error(client, demo_mcp):
    with pytest.raises(McpProtocolError):
        client.probe(demo_mcp.url.replace("/mcp", "/not-mcp"))


def test_url_policy_is_enforced_on_every_call(demo_mcp):
    strict = McpClient(UrlPolicy(), McpTimeouts(0.5, 0.75))
    with pytest.raises(McpUrlRejected):
        strict.probe(demo_mcp.url)


@pytest.mark.parametrize(
    "failure,expected",
    [
        (ExceptionGroup("g", [httpx2.ConnectError("refused")]), McpUnavailable),
        (ExceptionGroup("g", [ExceptionGroup("h", [httpx2.ReadTimeout("slow")])]), McpTimeout),
        (ExceptionGroup("g", [MCPError(-32001, "timed out")]), McpTimeout),
        (TimeoutError(), McpTimeout),
        (ExceptionGroup("g", [MCPError(-32601, "Not Found")]), McpProtocolError),
        (ExceptionGroup("g", [httpx2.ReadTimeout("x"), MCPError(-32001, "x")]), McpTimeout),
        (ExceptionGroup("g", [ValueError("garbage frame")]), McpProtocolError),
        (KeyError("unexpected"), McpProtocolError),
        (ExceptionGroup("g", [McpToolNotFound()]), McpToolNotFound),
    ],
)
def test_transport_failures_are_classified(failure, expected):
    error = classify(failure)
    assert isinstance(error, expected)
    assert "refused" not in error.message and "garbage" not in error.message
