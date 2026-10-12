import socket
import threading
import time

import anyio
import httpx2
import pytest
import uvicorn
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from nexusflow_mcp_demo.server import build_server, create_app

EXPECTED_TOOLS = {"search_customer", "calculate", "get_platform_info"}
FORBIDDEN = ("exec", "shell", "command", "file", "http", "env", "sql", "python")


def call(name, arguments=None):
    async def run():
        async with Client(build_server(), cache=None) as client:
            return await client.call_tool(name, arguments or {})

    return anyio.run(run)


def listing():
    async def run():
        async with Client(build_server(), cache=None) as client:
            return (await client.list_tools()).tools

    return anyio.run(run)


def test_discovery_exposes_only_the_three_demo_tools():
    tools = {tool.name: tool for tool in listing()}
    assert set(tools) == EXPECTED_TOOLS
    assert not any(word in name for name in tools for word in FORBIDDEN)
    for tool in tools.values():
        assert tool.description
        assert tool.input_schema["type"] == "object"
        assert tool.output_schema["type"] == "object"
    assert tools["calculate"].input_schema["required"] == ["operation", "a", "b"]


def test_search_customer_returns_labelled_demo_data():
    result = call("search_customer", {"company": "Acme Corporation"})
    assert result.is_error is False
    assert result.structured_content == {
        "found": True,
        "company": "Acme Corporation",
        "segment": "Enterprise",
        "status": "active",
        "account_owner": "Maya Chen",
        "region": "North America",
        "available": [],
        "source": "NexusFlow demo MCP data",
    }
    missing = call("search_customer", {"company": "Globex"}).structured_content
    assert missing["found"] is False
    assert "Acme Corporation" in missing["available"]


@pytest.mark.parametrize(
    "operation,a,b,expected",
    [
        ("multiply", 125, 24, "3000"),
        ("add", 2, 0, "2"),
        ("divide", 1, 3, "0.3333333333"),
        ("subtract", 2.5, 5, "-2.5"),
    ],
)
def test_calculate(operation, a, b, expected):
    result = call("calculate", {"operation": operation, "a": a, "b": b})
    assert result.structured_content["result"] == expected


def test_divide_by_zero_is_a_tool_error():
    result = call("calculate", {"operation": "divide", "a": 1, "b": 0})
    assert result.is_error is True
    assert "Division by zero is not allowed." in result.content[0].text


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "power", "a": 2, "b": 3},
        {"operation": "add", "a": "__import__('os')", "b": 1},
        {"operation": "add", "a": 1e13, "b": 1},
        {"operation": "add", "a": 1},
    ],
)
def test_calculate_rejects_invalid_input(arguments):
    assert call("calculate", arguments).is_error is True


def test_platform_info_reveals_no_environment():
    info = call("get_platform_info").structured_content
    assert info["service"] == "nexusflow-demo-mcp"
    assert info["status"] == "ok"
    assert info["protocol"] == "MCP"
    assert set(info["tools"]) == EXPECTED_TOOLS
    assert not {"host", "env", "path", "hostname", "database"} & set(info)


def test_unknown_tool_is_an_error():
    assert call("run_shell", {"command": "id"}).is_error is True


@pytest.fixture(scope="module")
def http_server():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app([f"127.0.0.1:{port}"]), host="127.0.0.1", port=port, log_level="error"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    yield port
    server.should_exit = True
    thread.join(5)


def over_http(url, operation):
    async def run():
        async with httpx2.AsyncClient(timeout=5) as http:
            async with Client(streamable_http_client(url, http_client=http), cache=None) as client:
                return await operation(client)

    return anyio.run(run)


def test_streamable_http_round_trip_and_health(http_server):
    url = f"http://127.0.0.1:{http_server}"

    async def operation(client):
        tools = await client.list_tools()
        result = await client.call_tool("calculate", {"operation": "multiply", "a": 125, "b": 24})
        return client.server_info.name, {tool.name for tool in tools.tools}, result

    name, tools, result = over_http(url + "/mcp", operation)
    assert name == "nexusflow-demo-mcp"
    assert tools == EXPECTED_TOOLS
    assert result.structured_content["result"] == "3000"
    assert httpx2.get(url + "/healthz").json() == {"status": "ok", "service": "nexusflow-demo-mcp"}


def test_unlisted_host_header_is_rejected(http_server):
    response = httpx2.post(
        f"http://127.0.0.1:{http_server}/mcp",
        headers={"Host": "evil.example", "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 421
