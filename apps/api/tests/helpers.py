"""Shared HTTP helpers for API tests."""

PASSWORD = "correct-horse-battery-staple"
AGENT = {
    "name": "Operations Assistant",
    "description": "Internal operations demonstration agent.",
    "instructions": "Help operators retrieve customer and platform information.",
}
NODES = ["analyze_request", "create_plan", "execute_demo_tool", "compose_response"]


def workspace(client, email="owner@example.com", organization="Organization A"):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "first_name": "Test",
            "last_name": "User",
            "organization_name": organization,
        },
    )
    assert response.status_code == 201
    data = response.json()
    return {
        "Authorization": "Bearer " + data["access_token"],
        "X-Organization-ID": data["user"]["organizations"][0]["id"],
    }


def create_agent(client, headers, activate=True, **overrides):
    response = client.post("/api/v1/agents", headers=headers, json={**AGENT, **overrides})
    assert response.status_code == 201
    agent = response.json()
    if activate:
        response = client.patch(
            f"/api/v1/agents/{agent['id']}", headers=headers, json={"status": "active"}
        )
        assert response.status_code == 200
        agent = response.json()
    return agent


def run(client, headers, agent_id, text):
    return client.post(f"/api/v1/agents/{agent_id}/runs", headers=headers, json={"input": text})


def events(client, headers, run_id):
    detail = client.get(f"/api/v1/agent-runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    return detail.json()["events"]


TEAM_ROLES = {
    "supervisor": "Enterprise Supervisor",
    "customer_specialist": "Customer Specialist",
    "researcher": "Research Agent",
    "analyst": "Opportunity Analyst",
    "writer": "Proposal Writer",
    "validator": "Quality Validator",
}
OBJECTIVE = (
    "Analyze Acme Corporation as a potential enterprise opportunity and recommend next steps."
)


def assign_tool(client, headers, agent_id, tool_key):
    return client.post(
        f"/api/v1/agents/{agent_id}/tools", headers=headers, json={"tool_key": tool_key}
    )


def build_team(
    client,
    headers,
    tool_key="internal:customer_lookup",
    roles=None,
    activate=True,
    name="Enterprise Account Intelligence Team",
):
    roles = roles or TEAM_ROLES
    agents = {role: create_agent(client, headers, name=agent) for role, agent in roles.items()}
    if tool_key and "customer_specialist" in agents:
        response = assign_tool(client, headers, agents["customer_specialist"]["id"], tool_key)
        assert response.status_code == 201, response.text
    response = client.post(
        "/api/v1/agent-teams",
        headers=headers,
        json={
            "name": name,
            "description": "Supervisor-led account intelligence team.",
            "members": [
                {"agent_id": agent["id"], "role": role, "position": index}
                for index, (role, agent) in enumerate(agents.items())
            ],
        },
    )
    assert response.status_code == 201, response.text
    team = response.json()
    if activate:
        response = client.patch(
            f"/api/v1/agent-teams/{team['id']}", headers=headers, json={"status": "active"}
        )
        assert response.status_code == 200, response.text
        team = response.json()
    return team, agents


def run_team(client, headers, team_id, objective=OBJECTIVE):
    return client.post(
        f"/api/v1/agent-teams/{team_id}/runs", headers=headers, json={"objective": objective}
    )
