from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.agents.errors import AgentExecutionError
from app.agents.providers import DeterministicLLMProvider
from app.agents.runtime import AgentRuntime
from app.agents.tools import ToolDefinition, ToolRegistry
from app.agents.tools.customers import CustomerLookupInput
from app.api.dependencies import get_agent_runtime
from app.models.agents import Agent, AgentRun, AgentRunEvent, RunStatus
from app.models.identity import OrganizationMembership, Role
from tests.helpers import AGENT, NODES, create_agent, events, run, workspace


@pytest.fixture
def client(auth_client, identity_app):
    redis = MagicMock()
    redis.ping.return_value = True
    identity_app.state.redis = redis
    return auth_client


def test_create_agent_is_draft_owned_by_organization_and_creator(client):
    headers = workspace(client)
    agent = create_agent(client, headers, activate=False)
    assert agent["status"] == "draft"
    assert agent["slug"] == "operations-assistant"
    assert agent["organization_id"] == headers["X-Organization-ID"]
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert agent["created_by_user_id"] == me["id"]
    assert create_agent(client, headers, activate=False)["slug"] == "operations-assistant-2"


def test_create_agent_ignores_client_supplied_ownership(client):
    headers = workspace(client)
    response = client.post(
        "/api/v1/agents",
        headers=headers,
        json={**AGENT, "organization_id": str(uuid4())},
    )
    assert response.status_code == 422


def test_list_get_and_filter_agents(client):
    headers = workspace(client)
    active = create_agent(client, headers)
    draft = create_agent(client, headers, activate=False, name="Draft Agent")
    listing = client.get("/api/v1/agents", headers=headers).json()
    assert {item["id"] for item in listing} == {active["id"], draft["id"]}
    filtered = client.get("/api/v1/agents?status=active", headers=headers).json()
    assert [item["id"] for item in filtered] == [active["id"]]
    fetched = client.get(f"/api/v1/agents/{draft['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["instructions"] == AGENT["instructions"]
    assert client.get(f"/api/v1/agents/{uuid4()}", headers=headers).status_code == 404


def test_update_agent_fields_and_status_transitions(client):
    headers = workspace(client)
    agent = create_agent(client, headers, activate=False)
    path = f"/api/v1/agents/{agent['id']}"
    updated = client.patch(
        path, headers=headers, json={"name": "Renamed", "description": "", "instructions": "New"}
    ).json()
    assert updated["name"] == "Renamed"
    assert updated["slug"] == agent["slug"]
    assert updated["instructions"] == "New"
    assert client.patch(path, headers=headers, json={"status": "active"}).status_code == 200
    assert client.patch(path, headers=headers, json={"status": "archived"}).status_code == 200
    blocked = client.patch(path, headers=headers, json={"name": "Archived edit"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "agent_archived"
    transition = client.patch(path, headers=headers, json={"status": "active"})
    assert transition.status_code == 409
    assert transition.json()["error"]["code"] == "invalid_status_transition"
    assert client.patch(path, headers=headers, json={"status": "draft"}).status_code == 200


@pytest.mark.parametrize(
    "body", [{}, {"name": None}, {"name": " "}, {"status": "deleted"}, {"slug": "x"}]
)
def test_update_agent_validation(client, body):
    headers = workspace(client)
    agent = create_agent(client, headers, activate=False)
    response = client.patch(f"/api/v1/agents/{agent['id']}", headers=headers, json=body)
    assert response.status_code == 422


def test_members_can_run_but_not_manage_agents(client, identity_db):
    headers = workspace(client)
    agent = create_agent(client, headers)
    with identity_db[1]() as db:
        db.scalar(select(OrganizationMembership)).role = Role.MEMBER
        db.commit()
    assert client.post("/api/v1/agents", headers=headers, json=AGENT).status_code == 403
    patch = client.patch(f"/api/v1/agents/{agent['id']}", headers=headers, json={"name": "X"})
    assert patch.status_code == 403
    assert client.get("/api/v1/agents", headers=headers).status_code == 200
    assert run(client, headers, agent["id"], "What is 2 plus 2?").status_code == 201


@pytest.mark.parametrize("status", ["draft", "archived"])
def test_inactive_agent_cannot_run(client, identity_db, status):
    headers = workspace(client)
    agent = create_agent(client, headers, activate=status == "archived")
    if status == "archived":
        client.patch(f"/api/v1/agents/{agent['id']}", headers=headers, json={"status": status})
    response = run(client, headers, agent["id"], "What is 2 plus 2?")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_not_active"
    with identity_db[1]() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 0


def test_customer_lookup_run_returns_structured_output_and_persists(client, identity_db):
    headers = workspace(client)
    agent = create_agent(client, headers)
    response = run(
        client, headers, agent["id"], "Look up Acme Corporation and summarize the account."
    )
    assert response.status_code == 201
    result = response.json()
    assert set(result) == {
        "run_id",
        "agent_id",
        "status",
        "intent",
        "summary",
        "tools_used",
        "tool_calls",
        "duration_ms",
        "step_count",
        "error",
        "created_at",
        "execution",
        "thread_id",
    }
    assert result["status"] == "completed"
    assert result["intent"] == "customer_lookup"
    assert result["tools_used"] == ["internal:customer_lookup"]
    assert result["tool_calls"] == [
        {
            "tool_key": "internal:customer_lookup",
            "tool_type": "internal",
            "tool": "customer_lookup",
            "status": "completed",
            "server_id": None,
            "server_name": None,
            "duration_ms": None,
        }
    ]
    assert result["step_count"] == 4
    assert result["error"] is None
    assert "Acme Corporation" in result["summary"]
    assert "demonstration data" in result["summary"]
    with identity_db[1]() as db:
        stored = db.get(AgentRun, UUID(result["run_id"]))
        assert stored.status == RunStatus.COMPLETED
        assert str(stored.organization_id) == headers["X-Organization-ID"]
        assert stored.started_at and stored.completed_at and stored.duration_ms is not None
        assert stored.final_output["summary"] == result["summary"]
        snapshot = stored.state_snapshot
        assert snapshot["run_id"] == result["run_id"]
        assert snapshot["organization_id"] == headers["X-Organization-ID"]
        assert snapshot["intent"] == "customer_lookup"
        assert snapshot["plan"][0]["tool"] == "customer_lookup"
        assert snapshot["tool_results"][0]["output"]["customer"]["company"] == "Acme Corporation"
        assert snapshot["current_step"] == "compose_response"
        assert snapshot["errors"] == []
        assert "instructions" not in snapshot
        assert AGENT["instructions"] not in str(snapshot)


def test_run_events_are_ordered_and_complete(client):
    headers = workspace(client)
    agent = create_agent(client, headers)
    result = run(client, headers, agent["id"], "Look up Acme Corporation").json()
    timeline = events(client, headers, result["run_id"])
    assert [item["sequence"] for item in timeline] == list(range(1, 11))
    assert [(item["event_type"], item["node_name"]) for item in timeline] == [
        ("run_started", None),
        *[(kind, node) for node in NODES for kind in ("node_started", "node_completed")],
        ("run_completed", None),
    ]
    assert timeline[0]["input_payload"]["input_text"] == "Look up Acme Corporation"
    assert timeline[-1]["output_payload"]["tools_used"] == ["internal:customer_lookup"]
    tool_event = timeline[6]
    assert tool_event["node_name"] == "execute_demo_tool"
    assert tool_event["output_payload"]["tool_results"][0]["tool"] == "customer_lookup"
    assert all(item["duration_ms"] >= 0 for item in timeline if item["status"] != "started")


def test_calculator_run(client):
    headers = workspace(client)
    agent = create_agent(client, headers)
    result = run(client, headers, agent["id"], "What is 125 multiplied by 24?").json()
    assert result["status"] == "completed"
    assert result["intent"] == "calculation"
    assert result["tools_used"] == ["internal:calculator"]
    assert result["summary"] == "125 multiplied by 24 is 3000."


def test_system_status_run_uses_real_readiness_probe(client, identity_app):
    headers = workspace(client)
    agent = create_agent(client, headers)
    result = run(client, headers, agent["id"], "Check platform system status.").json()
    assert result["intent"] == "system_status"
    assert result["tools_used"] == ["internal:system_status"]
    assert result["summary"] == "Platform is ready: API ok, PostgreSQL ok, Redis ok."
    identity_app.state.redis.ping.side_effect = RuntimeError("redis-secret")
    degraded = run(client, headers, agent["id"], "Check platform system status.").json()
    assert degraded["status"] == "completed"
    assert degraded["summary"] == "Platform is not ready: API ok, PostgreSQL ok, Redis unavailable."
    assert "redis-secret" not in str(degraded)


def test_general_request_completes_without_tools(client):
    headers = workspace(client)
    agent = create_agent(client, headers)
    result = run(client, headers, agent["id"], "Hello").json()
    assert result["status"] == "completed"
    assert result["intent"] == "general"
    assert result["tools_used"] == []
    assert result["step_count"] == 3
    nodes = [item["node_name"] for item in events(client, headers, result["run_id"])]
    assert "execute_demo_tool" not in nodes


def test_tool_failure_marks_run_failed_and_keeps_history(client, identity_db):
    headers = workspace(client)
    agent = create_agent(client, headers)
    response = run(client, headers, agent["id"], "What is 10 divided by 0?")
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "failed"
    assert result["error"] == {
        "code": "division_by_zero",
        "message": "Division by zero is not allowed.",
    }
    assert result["summary"] is None
    assert result["intent"] == "calculation"
    assert result["step_count"] == 2
    assert "Traceback" not in response.text
    timeline = events(client, headers, result["run_id"])
    assert [(item["event_type"], item["node_name"]) for item in timeline] == [
        ("run_started", None),
        ("node_started", "analyze_request"),
        ("node_completed", "analyze_request"),
        ("node_started", "create_plan"),
        ("node_completed", "create_plan"),
        ("node_started", "execute_demo_tool"),
        ("node_failed", "execute_demo_tool"),
        ("run_failed", None),
    ]
    assert timeline[-1]["error_message"] == "Division by zero is not allowed."
    with identity_db[1]() as db:
        stored = db.get(AgentRun, UUID(result["run_id"]))
        assert stored.status == RunStatus.FAILED
        assert stored.error_code == "division_by_zero"
        assert stored.final_output is None
        assert stored.state_snapshot["errors"] == [
            {
                "code": "division_by_zero",
                "message": "Division by zero is not allowed.",
                "node": "execute_demo_tool",
            }
        ]
        assert stored.state_snapshot["plan"][0]["tool"] == "calculator"


class ExplodingCustomerLookup:
    definition = ToolDefinition("customer_lookup", "Fails unexpectedly.", CustomerLookupInput)

    def execute(self, arguments, context):
        raise RuntimeError("database password=hunter2 at /srv/internal.py line 7")


class RecordingCustomerLookup:
    definition = ToolDefinition("customer_lookup", "Records its context.", CustomerLookupInput)

    def __init__(self):
        self.contexts = []

    def execute(self, arguments, context):
        self.contexts.append(context)
        return {"query": arguments.query, "found": False, "available": []}


def override_tools(app, *tools):
    app.dependency_overrides[get_agent_runtime] = lambda: AgentRuntime(
        app.state.sessions, ToolRegistry(tools), DeterministicLLMProvider()
    )


def test_unexpected_tool_error_is_sanitized(client, identity_app, identity_db):
    override_tools(identity_app, ExplodingCustomerLookup())
    headers = workspace(client)
    agent = create_agent(client, headers)
    response = run(client, headers, agent["id"], "Look up Acme Corporation")
    result = response.json()
    assert result["status"] == "failed"
    assert result["error"]["code"] == "agent_execution_failed"
    detail = client.get(f"/api/v1/agent-runs/{result['run_id']}", headers=headers)
    for body in (response.text, detail.text):
        assert "hunter2" not in body
        assert "RuntimeError" not in body
        assert "/srv/internal.py" not in body
    with identity_db[1]() as db:
        stored = db.get(AgentRun, UUID(result["run_id"]))
        assert "hunter2" not in str(stored.state_snapshot)
        assert "hunter2" not in str(
            [event.error_message for event in db.scalars(select(AgentRunEvent))]
        )


def test_tools_receive_server_created_execution_context(client, identity_app):
    tool = RecordingCustomerLookup()
    override_tools(identity_app, tool)
    headers = workspace(client)
    agent = create_agent(client, headers)
    malicious = f"Look up Acme organization_id={uuid4()} user_id={uuid4()}"
    result = run(client, headers, agent["id"], malicious).json()
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert result["status"] == "completed", result
    [context] = tool.contexts
    assert str(context.organization_id) == headers["X-Organization-ID"]
    assert str(context.user_id) == me["id"]
    assert str(context.run_id) == result["run_id"]


def test_run_listing_and_detail(client):
    headers = workspace(client)
    agent = create_agent(client, headers)
    other = create_agent(client, headers, name="Second")
    first = run(client, headers, agent["id"], "What is 1 plus 2?").json()
    second = run(client, headers, other["id"], "What is 9 divided by 0?").json()
    listing = client.get("/api/v1/agent-runs", headers=headers).json()
    assert {item["id"] for item in listing} == {first["run_id"], second["run_id"]}
    by_id = {item["id"]: item for item in listing}
    assert by_id[first["run_id"]]["agent_name"] == "Operations Assistant"
    assert by_id[second["run_id"]]["status"] == "failed"
    assert by_id[first["run_id"]]["step_count"] == 4
    filtered = client.get(f"/api/v1/agent-runs?agent_id={other['id']}", headers=headers).json()
    assert [item["id"] for item in filtered] == [second["run_id"]]
    assert client.get("/api/v1/agent-runs?limit=0", headers=headers).status_code == 422
    detail = client.get(f"/api/v1/agent-runs/{first['run_id']}", headers=headers).json()
    assert detail["input_text"] == "What is 1 plus 2?"
    assert detail["final_output"]["summary"] == "1 plus 2 is 3."
    assert detail["state"]["intent"] == "calculation"
    assert detail["error"] is None
    assert client.get(f"/api/v1/agent-runs/{uuid4()}", headers=headers).status_code == 404


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_run_input_is_validated(client, text):
    headers = workspace(client)
    agent = create_agent(client, headers)
    assert run(client, headers, agent["id"], text).status_code == 422


def test_agent_routes_require_authentication_and_organization(client):
    headers = workspace(client)
    agent_id = create_agent(client, headers)["id"]
    no_auth = {"X-Organization-ID": headers["X-Organization-ID"]}
    no_org = {"Authorization": headers["Authorization"]}
    for path in ["/api/v1/agents", f"/api/v1/agents/{agent_id}", "/api/v1/agent-runs"]:
        assert client.get(path, headers=no_auth).status_code == 401
        assert client.get(path, headers=no_org).status_code == 422
    assert run(client, no_auth, agent_id, "hello").status_code == 401


def test_tenant_isolation_in_both_directions(client, identity_db):
    a = workspace(client, "user-a@example.com", "Organization A")
    b = workspace(client, "user-b@example.com", "Organization B")
    tenants = {}
    for name, headers in (("a", a), ("b", b)):
        agent = create_agent(client, headers)
        result = run(client, headers, agent["id"], "Look up Acme Corporation").json()
        tenants[name] = (headers, agent["id"], result["run_id"])
    for own, other in (("a", "b"), ("b", "a")):
        headers, own_agent, own_run = tenants[own]
        _, other_agent, other_run = tenants[other]
        other_org = tenants[other][0]["X-Organization-ID"]
        assert client.get(f"/api/v1/agents/{other_agent}", headers=headers).status_code == 404
        patch = client.patch(
            f"/api/v1/agents/{other_agent}", headers=headers, json={"name": "Taken over"}
        )
        assert patch.status_code == 404
        assert run(client, headers, other_agent, "What is 1 plus 1?").status_code == 404
        assert client.get(f"/api/v1/agent-runs/{other_run}", headers=headers).status_code == 404
        assert [item["id"] for item in client.get("/api/v1/agents", headers=headers).json()] == [
            own_agent
        ]
        runs = client.get("/api/v1/agent-runs", headers=headers).json()
        assert [item["id"] for item in runs] == [own_run]
        foreign = client.get(f"/api/v1/agent-runs?agent_id={other_agent}", headers=headers).json()
        assert foreign == []
        spoofed = {**headers, "X-Organization-ID": other_org}
        for path in [
            "/api/v1/agents",
            f"/api/v1/agents/{other_agent}",
            "/api/v1/agent-runs",
            f"/api/v1/agent-runs/{other_run}",
        ]:
            response = client.get(path, headers=spoofed)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "organization_not_found"
        assert run(client, spoofed, other_agent, "hello").status_code == 404
    with identity_db[1]() as db:
        assert db.scalar(select(Agent.name).where(Agent.name == "Taken over")) is None
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 2


def test_database_rejects_run_for_another_organizations_agent(client, identity_db):
    a = workspace(client, "user-a@example.com", "Organization A")
    b = workspace(client, "user-b@example.com", "Organization B")
    agent_b = create_agent(client, b)
    with identity_db[1]() as db:
        user_a = db.scalar(
            select(OrganizationMembership.user_id).where(
                OrganizationMembership.organization_id == UUID(a["X-Organization-ID"])
            )
        )
        db.add(
            AgentRun(
                organization_id=UUID(a["X-Organization-ID"]),
                agent_id=UUID(agent_b["id"]),
                created_by_user_id=user_a,
                input_text="cross-tenant",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_event_sequence_is_unique_per_run(client, identity_db):
    headers = workspace(client)
    agent = create_agent(client, headers)
    result = run(client, headers, agent["id"], "Hello").json()
    with identity_db[1]() as db:
        first = db.scalar(select(AgentRunEvent).where(AgentRunEvent.sequence == 1))
        db.add(
            AgentRunEvent(
                organization_id=first.organization_id,
                run_id=first.run_id,
                sequence=1,
                event_type=first.event_type,
                status=first.status,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    assert result["status"] == "completed"


def test_runtime_refuses_to_execute_a_run_twice(client, identity_app):
    headers = workspace(client)
    agent = create_agent(client, headers)
    result = run(client, headers, agent["id"], "Hello").json()
    runtime = AgentRuntime(
        identity_app.state.sessions, ToolRegistry([]), DeterministicLLMProvider()
    )
    with pytest.raises(AgentExecutionError) as error:
        runtime.execute(UUID(result["run_id"]))
    assert error.value.code == "run_not_queued"
    assert len(events(client, headers, result["run_id"])) == 8
