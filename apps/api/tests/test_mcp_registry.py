from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.identity import OrganizationMembership, Role
from app.models.mcp import McpServer, McpTool
from tests.helpers import workspace

DEMO_TOOLS = {"search_customer", "calculate", "get_platform_info"}


@pytest.fixture
def client(auth_client, mcp_app):
    return auth_client


def register_server(client, headers, url, name="NexusFlow Demo Tools", **extra):
    response = client.post(
        "/api/v1/mcp-servers",
        headers=headers,
        json={
            "name": name,
            "description": "Internal demonstration MCP server",
            "url": url,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def discover(client, headers, server_id):
    return client.post(f"/api/v1/mcp-servers/{server_id}/discover", headers=headers)


def test_register_server_starts_pending_with_slug(client, demo_mcp):
    headers = workspace(client)
    server = register_server(client, headers, demo_mcp.url)
    assert server["status"] == "pending"
    assert server["slug"] == "nexusflow-demo-tools"
    assert server["transport"] == "streamable_http"
    assert server["is_enabled"] is True
    assert server["tool_count"] == 0
    assert server["organization_id"] == headers["X-Organization-ID"]
    assert register_server(client, headers, demo_mcp.url)["slug"] == "nexusflow-demo-tools-2"


@pytest.mark.parametrize(
    "body",
    [
        {"transport": "stdio"},
        {"transport": "sse"},
        {"organization_id": str(uuid4())},
        {"status": "connected"},
    ],
)
def test_register_rejects_unsupported_fields(client, demo_mcp, body):
    headers = workspace(client)
    response = client.post(
        "/api/v1/mcp-servers",
        headers=headers,
        json={"name": "Server", "url": demo_mcp.url, **body},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8765/mcp",
        "http://localhost:8765/mcp",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/mcp",
        "file:///etc/passwd",
        "gopher://127.0.0.1:6379/_",
        "https://example.com/mcp",
    ],
)
def test_register_rejects_unsafe_urls(client, identity_db, url):
    headers = workspace(client)
    response = client.post(
        "/api/v1/mcp-servers", headers=headers, json={"name": "Unsafe", "url": url}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "mcp_url_rejected"
    with identity_db[1]() as db:
        assert db.scalar(select(func.count()).select_from(McpServer)) == 0


def test_connection_test_reports_server_and_persists_status(client, demo_mcp):
    headers = workspace(client)
    server = register_server(client, headers, demo_mcp.url)
    result = client.post(f"/api/v1/mcp-servers/{server['id']}/test", headers=headers).json()
    assert result["status"] == "connected"
    assert result["server"] == "nexusflow-demo-mcp"
    assert result["protocol_version"]
    assert result["duration_ms"] >= 0
    assert result["error"] is None
    stored = client.get(f"/api/v1/mcp-servers/{server['id']}", headers=headers).json()
    assert stored["status"] == "connected"
    assert stored["last_connected_at"] is not None


def test_connection_failure_is_safe_and_persisted(client, closed_port):
    headers = workspace(client)
    server = register_server(client, headers, f"http://127.0.0.1:{closed_port}/mcp")
    result = client.post(f"/api/v1/mcp-servers/{server['id']}/test", headers=headers).json()
    assert result == {
        "status": "unavailable",
        "server": None,
        "version": None,
        "protocol_version": None,
        "duration_ms": 0,
        "error": {"code": "mcp_unavailable", "message": "The MCP server could not be reached."},
    }
    stored = client.get(f"/api/v1/mcp-servers/{server['id']}", headers=headers).json()
    assert stored["status"] == "unavailable"
    assert stored["last_error_code"] == "mcp_unavailable"
    assert "Traceback" not in str(stored) and "ConnectError" not in str(stored)


def test_discovery_persists_live_tools(client, demo_mcp, identity_db):
    headers = workspace(client)
    server = register_server(client, headers, demo_mcp.url)
    response = discover(client, headers, server["id"])
    assert response.status_code == 200
    data = response.json()
    assert set(data["added"]) == DEMO_TOOLS
    assert data["updated"] == data["removed"] == []
    assert data["server"]["tool_count"] == 3
    assert data["server"]["last_discovered_at"] is not None
    keys = {tool["tool_key"] for tool in data["tools"]}
    assert keys == {f"mcp:nexusflow-demo-tools:{name}" for name in DEMO_TOOLS}
    listed = client.get(f"/api/v1/mcp-servers/{server['id']}/tools", headers=headers).json()
    calculate = next(tool for tool in listed if tool["name"] == "calculate")
    assert calculate["input_schema"]["required"] == ["operation", "a", "b"]
    assert calculate["output_schema"]["type"] == "object"
    assert calculate["is_enabled"] and calculate["is_available"]
    again = discover(client, headers, server["id"]).json()
    assert again["added"] == again["updated"] == again["removed"] == []
    with identity_db[1]() as db:
        assert db.scalar(select(func.count()).select_from(McpTool)) == 3


class Upper(BaseModel):
    value: str


def test_rediscovery_adds_updates_and_retires_tools(client, mutable_mcp):
    headers = workspace(client)
    server = register_server(client, headers, mutable_mcp.url, name="Mutable")
    first = discover(client, headers, server["id"]).json()
    assert set(first["added"]) == {"echo", "slow"}
    tools = {tool["name"]: tool for tool in first["tools"]}
    client.patch(
        f"/api/v1/mcp-servers/{server['id']}/tools/{tools['slow']['id']}",
        headers=headers,
        json={"is_enabled": False},
    )

    mcp = mutable_mcp.server
    mcp.remove_tool("echo")

    @mcp.tool(name="echo", description="Echo a value, revised.")
    def echo(value: str, times: int = 1) -> Upper:
        return Upper(value=value * times)

    @mcp.tool()
    def upper(value: str) -> Upper:
        """Uppercase a value."""
        return Upper(value=value.upper())

    mcp.remove_tool("slow")
    second = discover(client, headers, server["id"]).json()
    assert second["added"] == ["upper"]
    assert second["updated"] == ["echo"]
    assert second["removed"] == ["slow"]
    listed = {
        tool["name"]: tool
        for tool in client.get(f"/api/v1/mcp-servers/{server['id']}/tools", headers=headers).json()
    }
    assert listed["echo"]["description"] == "Echo a value, revised."
    assert "times" in listed["echo"]["input_schema"]["properties"]
    assert listed["slow"]["is_available"] is False
    assert listed["slow"]["is_enabled"] is False
    assert second["server"]["tool_count"] == 2

    @mcp.tool()
    def slow() -> Upper:
        """Back again."""
        return Upper(value="back")

    third = discover(client, headers, server["id"]).json()
    assert "slow" in third["updated"]
    restored = next(tool for tool in third["tools"] if tool["name"] == "slow")
    assert restored["is_available"] is True
    assert restored["is_enabled"] is False  # operator choice survives rediscovery


def test_discovery_failure_is_reported_and_persisted(client, closed_port):
    headers = workspace(client)
    server = register_server(client, headers, f"http://127.0.0.1:{closed_port}/mcp")
    response = discover(client, headers, server["id"])
    assert response.status_code == 502
    assert response.json()["error"] == {
        "code": "mcp_unavailable",
        "message": "The MCP server could not be reached.",
    }
    stored = client.get(f"/api/v1/mcp-servers/{server['id']}", headers=headers).json()
    assert stored["status"] == "unavailable"


def test_disabled_server_cannot_be_tested_or_discovered(client, demo_mcp):
    headers = workspace(client)
    server = register_server(client, headers, demo_mcp.url)
    path = f"/api/v1/mcp-servers/{server['id']}"
    disabled = client.patch(path, headers=headers, json={"is_enabled": False}).json()
    assert disabled["status"] == "disabled"
    for action in ("test", "discover"):
        response = client.post(f"{path}/{action}", headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "mcp_server_disabled"
    assert client.patch(path, headers=headers, json={"is_enabled": True}).json()["status"] == (
        "pending"
    )


def test_changing_url_revalidates_and_retires_tools(client, demo_mcp, mutable_mcp):
    headers = workspace(client)
    server = register_server(client, headers, demo_mcp.url)
    discover(client, headers, server["id"])
    path = f"/api/v1/mcp-servers/{server['id']}"
    rejected = client.patch(path, headers=headers, json={"url": "http://169.254.169.254/"})
    assert rejected.status_code == 422
    moved = client.patch(path, headers=headers, json={"url": mutable_mcp.url}).json()
    assert moved["status"] == "pending"
    assert moved["tool_count"] == 0
    assert moved["last_discovered_at"] is None
    tools = client.get(f"{path}/tools", headers=headers).json()
    assert tools and not any(tool["is_available"] for tool in tools)


@pytest.mark.parametrize("body", [{}, {"name": None}, {"transport": "stdio"}, {"url": None}])
def test_update_validation(client, demo_mcp, body):
    headers = workspace(client)
    server = register_server(client, headers, demo_mcp.url)
    response = client.patch(f"/api/v1/mcp-servers/{server['id']}", headers=headers, json=body)
    assert response.status_code == 422


def test_members_can_read_but_not_manage(client, demo_mcp, identity_db):
    headers = workspace(client)
    server = register_server(client, headers, demo_mcp.url)
    tool = discover(client, headers, server["id"]).json()["tools"][0]
    with identity_db[1]() as db:
        db.scalar(select(OrganizationMembership)).role = Role.MEMBER
        db.commit()
    path = f"/api/v1/mcp-servers/{server['id']}"
    assert client.get("/api/v1/mcp-servers", headers=headers).status_code == 200
    assert client.get(path, headers=headers).status_code == 200
    assert client.get(f"{path}/tools", headers=headers).status_code == 200
    denied = [
        client.post(
            "/api/v1/mcp-servers", headers=headers, json={"name": "X", "url": demo_mcp.url}
        ),
        client.patch(path, headers=headers, json={"name": "X"}),
        client.post(f"{path}/test", headers=headers),
        client.post(f"{path}/discover", headers=headers),
        client.patch(f"{path}/tools/{tool['id']}", headers=headers, json={"is_enabled": False}),
    ]
    assert [response.status_code for response in denied] == [403] * 5


def test_mcp_routes_require_authentication_and_organization(client, demo_mcp):
    headers = workspace(client)
    server = register_server(client, headers, demo_mcp.url)
    no_auth = {"X-Organization-ID": headers["X-Organization-ID"]}
    no_org = {"Authorization": headers["Authorization"]}
    for path in ["/api/v1/mcp-servers", f"/api/v1/mcp-servers/{server['id']}"]:
        assert client.get(path, headers=no_auth).status_code == 401
        assert client.get(path, headers=no_org).status_code == 422


def test_tenant_isolation_in_both_directions(client, demo_mcp, identity_db):
    tenants = {}
    for label in ("a", "b"):
        headers = workspace(client, f"user-{label}@example.com", f"Organization {label.upper()}")
        server = register_server(client, headers, demo_mcp.url, name=f"Server {label.upper()}")
        tool = discover(client, headers, server["id"]).json()["tools"][0]
        tenants[label] = (headers, server["id"], tool["id"])
    for own, other in (("a", "b"), ("b", "a")):
        headers, own_server, _ = tenants[own]
        other_headers, other_server, other_tool = tenants[other]
        path = f"/api/v1/mcp-servers/{other_server}"
        responses = {
            "read": client.get(path, headers=headers),
            "update": client.patch(path, headers=headers, json={"name": "Taken over"}),
            "test": client.post(f"{path}/test", headers=headers),
            "discover": client.post(f"{path}/discover", headers=headers),
            "tools": client.get(f"{path}/tools", headers=headers),
            "toggle": client.patch(
                f"{path}/tools/{other_tool}", headers=headers, json={"is_enabled": False}
            ),
            "own server, foreign tool": client.patch(
                f"/api/v1/mcp-servers/{own_server}/tools/{other_tool}",
                headers=headers,
                json={"is_enabled": False},
            ),
        }
        for action, response in responses.items():
            assert response.status_code == 404, action
            assert "Server " + other.upper() not in response.text
        listing = client.get("/api/v1/mcp-servers", headers=headers).json()
        assert [server["id"] for server in listing] == [own_server]
        spoofed = {**headers, "X-Organization-ID": other_headers["X-Organization-ID"]}
        assert client.get(path, headers=spoofed).status_code == 404
        assert client.get("/api/v1/mcp-servers", headers=spoofed).json()["error"]["code"] == (
            "organization_not_found"
        )
    with identity_db[1]() as db:
        assert db.scalar(select(McpServer).where(McpServer.name == "Taken over")) is None
        assert not db.scalar(select(func.count()).where(McpTool.is_enabled.is_(False)))


def test_database_ties_tools_to_their_servers_organization(client, demo_mcp, identity_db):
    a = workspace(client, "user-a@example.com", "Organization A")
    b = workspace(client, "user-b@example.com", "Organization B")
    server_b = register_server(client, b, demo_mcp.url)
    with identity_db[1]() as db:
        db.add(
            McpTool(
                organization_id=UUID(a["X-Organization-ID"]),
                mcp_server_id=UUID(server_b["id"]),
                name="smuggled",
                input_schema={"type": "object"},
                discovered_at=func.now(),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
