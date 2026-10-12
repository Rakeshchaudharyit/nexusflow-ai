from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.identity import OrganizationMembership, Role
from app.models.mcp import McpTool
from app.models.teams import AgentTeamMember, AgentTool, TeamRole
from tests.helpers import TEAM_ROLES, assign_tool, build_team, create_agent, workspace


@pytest.fixture
def client(auth_client, mcp_app):
    return auth_client


def discover_demo(client, headers, url):
    server = client.post(
        "/api/v1/mcp-servers", headers=headers, json={"name": "NexusFlow Demo Tools", "url": url}
    ).json()
    response = client.post(f"/api/v1/mcp-servers/{server['id']}/discover", headers=headers)
    assert response.status_code == 200
    return response.json()


def test_create_team_with_members_and_activate(client):
    headers = workspace(client)
    team, agents = build_team(client, headers, activate=False)
    assert team["status"] == "draft"
    assert team["slug"] == "enterprise-account-intelligence-team"
    assert team["member_count"] == 6
    assert team["problems"] == []
    roles = {member["role"]: member for member in team["members"]}
    assert set(roles) == set(TEAM_ROLES)
    assert roles["customer_specialist"]["tools"][0]["tool_key"] == "internal:customer_lookup"
    assert roles["supervisor"]["tools"] == []
    activated = client.patch(
        f"/api/v1/agent-teams/{team['id']}", headers=headers, json={"status": "active"}
    )
    assert activated.json()["status"] == "active"
    listing = client.get("/api/v1/agent-teams", headers=headers).json()
    assert [(item["id"], item["member_count"]) for item in listing] == [(team["id"], 6)]
    detail = client.get(f"/api/v1/agent-teams/{team['id']}", headers=headers).json()
    assert detail["members"][0]["agent_name"] == "Enterprise Supervisor"


@pytest.mark.parametrize(
    "roles,problem",
    [
        ({"customer_specialist": "C", "writer": "W", "validator": "V"}, "exactly one supervisor"),
        ({"supervisor": "S", "writer": "W", "validator": "V"}, "at least one specialist"),
        ({"supervisor": "S", "researcher": "R", "validator": "V"}, "a writer is required"),
        ({"supervisor": "S", "researcher": "R", "writer": "W"}, "a validator is required"),
    ],
)
def test_incomplete_team_cannot_be_activated(client, roles, problem):
    headers = workspace(client)
    team, _ = build_team(client, headers, roles=roles, activate=False, tool_key=None)
    assert any(problem in item for item in team["problems"])
    response = client.patch(
        f"/api/v1/agent-teams/{team['id']}", headers=headers, json={"status": "active"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "team_invalid"
    assert problem in response.json()["error"]["message"]


def test_inactive_member_agent_blocks_activation(client):
    headers = workspace(client)
    team, agents = build_team(client, headers, activate=False)
    client.patch(
        f"/api/v1/agents/{agents['writer']['id']}", headers=headers, json={"status": "draft"}
    )
    response = client.patch(
        f"/api/v1/agent-teams/{team['id']}", headers=headers, json={"status": "active"}
    )
    assert response.status_code == 409
    assert "Proposal Writer" in response.json()["error"]["message"]


def test_supervisor_and_roles_are_unique(client, identity_db):
    headers = workspace(client)
    team, agents = build_team(client, headers, activate=False)
    extra = create_agent(client, headers, name="Second Supervisor")
    path = f"/api/v1/agent-teams/{team['id']}/members"
    second = client.post(
        path, headers=headers, json={"agent_id": extra["id"], "role": "supervisor"}
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "team_member_conflict"
    duplicate_agent = client.post(
        path, headers=headers, json={"agent_id": agents["writer"]["id"], "role": "researcher"}
    )
    assert duplicate_agent.status_code == 409
    with identity_db[1]() as db:
        member = db.scalar(select(AgentTeamMember).where(AgentTeamMember.role == TeamRole.WRITER))
        db.add(
            AgentTeamMember(
                organization_id=member.organization_id,
                team_id=member.team_id,
                agent_id=UUID(extra["id"]),
                role=TeamRole.SUPERVISOR,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_member_changes_on_active_team_must_keep_it_valid(client):
    headers = workspace(client)
    team, _ = build_team(client, headers)
    members = {member["role"]: member for member in team["members"]}
    path = f"/api/v1/agent-teams/{team['id']}/members"
    removed = client.delete(f"{path}/{members['validator']['id']}", headers=headers)
    assert removed.status_code == 409
    assert "a validator is required" in removed.json()["error"]["message"]
    optional = client.patch(
        f"{path}/{members['researcher']['id']}", headers=headers, json={"is_required": False}
    )
    assert optional.status_code == 200
    researcher = next(m for m in optional.json()["members"] if m["role"] == "researcher")
    assert researcher["is_required"] is False
    assert (
        client.delete(f"{path}/{members['researcher']['id']}", headers=headers).status_code == 200
    )


def test_team_status_transitions_and_archive(client):
    headers = workspace(client)
    team, agents = build_team(client, headers)
    path = f"/api/v1/agent-teams/{team['id']}"
    assert client.patch(path, headers=headers, json={"status": "archived"}).status_code == 200
    blocked = client.patch(path, headers=headers, json={"name": "Renamed"})
    assert blocked.json()["error"]["code"] == "team_archived"
    assert client.patch(path, headers=headers, json={"status": "active"}).status_code == 409
    member = client.post(
        f"{path}/members",
        headers=headers,
        json={"agent_id": create_agent(client, headers, name="Late")["id"], "role": "analyst"},
    )
    assert member.status_code == 409
    restored = client.patch(path, headers=headers, json={"status": "draft", "name": "Renamed"})
    assert restored.status_code == 409  # restore first, then edit
    assert client.patch(path, headers=headers, json={"status": "draft"}).status_code == 200
    assert client.patch(path, headers=headers, json={"name": "Renamed"}).json()["name"] == "Renamed"


@pytest.mark.parametrize("body", [{}, {"name": None}, {"status": "deleted"}, {"slug": "x"}])
def test_team_update_validation(client, body):
    headers = workspace(client)
    team, _ = build_team(client, headers, activate=False)
    response = client.patch(f"/api/v1/agent-teams/{team['id']}", headers=headers, json=body)
    assert response.status_code == 422


def test_members_may_read_and_run_but_not_manage(client, identity_db):
    headers = workspace(client)
    team, agents = build_team(client, headers)
    with identity_db[1]() as db:
        db.scalar(select(OrganizationMembership)).role = Role.MEMBER
        db.commit()
    path = f"/api/v1/agent-teams/{team['id']}"
    assert client.get(path, headers=headers).status_code == 200
    assert client.get("/api/v1/agent-teams", headers=headers).status_code == 200
    denied = [
        client.post("/api/v1/agent-teams", headers=headers, json={"name": "X"}),
        client.patch(path, headers=headers, json={"name": "X"}),
        client.post(
            f"{path}/members", headers=headers, json={"agent_id": str(uuid4()), "role": "analyst"}
        ),
        assign_tool(client, headers, agents["writer"]["id"], "internal:calculator"),
    ]
    assert [response.status_code for response in denied] == [403] * 4
    run = client.post(
        f"{path}/runs", headers=headers, json={"objective": "Analyze Acme Corporation"}
    )
    assert run.status_code == 201


def test_tool_assignment_internal_and_mcp(client, demo_mcp):
    headers = workspace(client)
    discover_demo(client, headers, demo_mcp.url)
    agent = create_agent(client, headers, name="Customer Specialist")
    internal = assign_tool(client, headers, agent["id"], "internal:customer_lookup")
    mcp = assign_tool(client, headers, agent["id"], "mcp:nexusflow-demo-tools:search_customer")
    assert internal.status_code == mcp.status_code == 201
    assert mcp.json()["tool_type"] == "mcp"
    assert assign_tool(client, headers, agent["id"], "internal:customer_lookup").status_code == 409
    tools = client.get(f"/api/v1/agents/{agent['id']}/tools", headers=headers).json()
    assert [tool["tool_key"] for tool in tools] == [
        "internal:customer_lookup",
        "mcp:nexusflow-demo-tools:search_customer",
    ]
    catalog = {
        entry["tool_key"]: entry for entry in client.get("/api/v1/tools", headers=headers).json()
    }
    assert catalog["internal:calculator"]["tool_type"] == "internal"
    assert catalog["mcp:nexusflow-demo-tools:calculate"]["server_name"] == "NexusFlow Demo Tools"
    disabled = client.patch(
        f"/api/v1/agents/{agent['id']}/tools/{tools[0]['id']}",
        headers=headers,
        json={"is_enabled": False},
    )
    assert disabled.json()["is_enabled"] is False
    removed = client.delete(f"/api/v1/agents/{agent['id']}/tools/{tools[1]['id']}", headers=headers)
    assert removed.status_code == 204


@pytest.mark.parametrize(
    "key",
    [
        "internal:run_shell",
        "internal:",
        "mcp:nexusflow-demo-tools:run_shell",
        "mcp:missing-server:search_customer",
        "mcp:nexusflow-demo-tools",
        "http://evil.example/tool",
        "customer_lookup",
    ],
)
def test_invalid_tool_keys_are_rejected(client, demo_mcp, key):
    headers = workspace(client)
    discover_demo(client, headers, demo_mcp.url)
    agent = create_agent(client, headers)
    response = assign_tool(client, headers, agent["id"], key)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_tool_key"


def test_tenant_isolation_in_both_directions(client, demo_mcp, identity_db):
    tenants = {}
    for label in ("a", "b"):
        headers = workspace(client, f"user-{label}@example.com", f"Organization {label.upper()}")
        discover_demo(client, headers, demo_mcp.url)
        team, agents = build_team(
            client, headers, tool_key="mcp:nexusflow-demo-tools:search_customer"
        )
        run = client.post(
            f"/api/v1/agent-teams/{team['id']}/runs",
            headers=headers,
            json={"objective": "Analyze Acme Corporation"},
        ).json()
        tenants[label] = (headers, team, agents, run)
    for own, other in (("a", "b"), ("b", "a")):
        headers, own_team, own_agents, own_run = tenants[own]
        other_headers, team, agents, run = tenants[other]
        path = f"/api/v1/agent-teams/{team['id']}"
        member_id = team["members"][0]["id"]
        writer = agents["writer"]["id"]
        responses = {
            "read team": client.get(path, headers=headers),
            "edit team": client.patch(path, headers=headers, json={"name": "Taken"}),
            "add member": client.post(
                f"{path}/members",
                headers=headers,
                json={"agent_id": own_agents["writer"]["id"], "role": "analyst"},
            ),
            "edit member": client.patch(
                f"{path}/members/{member_id}", headers=headers, json={"is_required": False}
            ),
            "remove member": client.delete(f"{path}/members/{member_id}", headers=headers),
            "run team": client.post(
                f"{path}/runs", headers=headers, json={"objective": "Analyze Acme"}
            ),
            "read run": client.get(f"/api/v1/agent-team-runs/{run['run_id']}", headers=headers),
            "read tools": client.get(f"/api/v1/agents/{writer}/tools", headers=headers),
            "assign tool": assign_tool(client, headers, writer, "internal:calculator"),
        }
        for action, response in responses.items():
            assert response.status_code == 404, action
        # Own team cannot take in the other organization's agent.
        foreign_member = client.post(
            f"/api/v1/agent-teams/{own_team['id']}/members",
            headers=headers,
            json={"agent_id": writer, "role": "analyst"},
        )
        assert foreign_member.status_code == 422
        create = client.post(
            "/api/v1/agent-teams",
            headers=headers,
            json={"name": "Smuggler", "members": [{"agent_id": writer, "role": "supervisor"}]},
        )
        assert create.status_code == 422
        assert [t["id"] for t in client.get("/api/v1/agent-teams", headers=headers).json()] == [
            own_team["id"]
        ]
        runs = client.get("/api/v1/agent-team-runs", headers=headers).json()
        assert [item["id"] for item in runs] == [own_run["run_id"]]
        assert (
            client.get(f"/api/v1/agent-team-runs?team_id={team['id']}", headers=headers).json()
            == []
        )
        spoofed = {**headers, "X-Organization-ID": other_headers["X-Organization-ID"]}
        assert client.get(path, headers=spoofed).status_code == 404
    with identity_db[1]() as db:
        tools = db.scalars(select(AgentTool)).all()
        assert {tool.tool_key for tool in tools} == {"mcp:nexusflow-demo-tools:search_customer"}
        assert len(tools) == 2


def test_database_rejects_cross_tenant_members_and_tools(client, demo_mcp, identity_db):
    a = workspace(client, "user-a@example.com", "Organization A")
    b = workspace(client, "user-b@example.com", "Organization B")
    discover_demo(client, b, demo_mcp.url)
    team_a, agents_a = build_team(client, a, activate=False)
    agent_b = create_agent(client, b)
    with identity_db[1]() as db:
        db.add(
            AgentTeamMember(
                organization_id=UUID(a["X-Organization-ID"]),
                team_id=UUID(team_a["id"]),
                agent_id=UUID(agent_b["id"]),
                role=TeamRole.ANALYST,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    with identity_db[1]() as db:
        tool_b = db.scalar(select(McpTool).where(McpTool.name == "search_customer"))
        db.add(
            AgentTool(
                organization_id=UUID(a["X-Organization-ID"]),
                agent_id=UUID(agents_a["writer"]["id"]),
                tool_key="mcp:nexusflow-demo-tools:search_customer",
                mcp_tool_id=tool_b.id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
