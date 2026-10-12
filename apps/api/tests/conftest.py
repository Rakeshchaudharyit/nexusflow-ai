import os
from typing import Annotated
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import require_organization_role
from app.core.config import Settings
from app.db.session import Base
from app.main import create_app
from app.models.identity import OrganizationMembership, Role
from tests.mcp_support import build_mutable_server, free_port, http_app, serve


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-signing-key-with-more-than-32-bytes")
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(name, "false")


@pytest.fixture
def identity_db():
    url = os.getenv("TEST_DATABASE_URL")
    if url:
        engine = create_engine(url, pool_pre_ping=True)
        schema = "test_m2_" + uuid4().hex
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(engine, "connect")
        def sqlite_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, sessions
    finally:
        if url:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        else:
            Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def identity_app(identity_db):
    engine, sessions = identity_db
    # Inline execution runs the real JobExecutor (claim, heartbeat, retry) inside the request,
    # so M1-M6 tests keep asserting final outcomes; M7 tests switch to a recording queue.
    settings = Settings(
        _env_file=None,
        postgres_password="test-only-password",
        app_env="test",
        execution_mode="inline",
        job_retry_base_seconds=0,
    )
    app = create_app(settings)
    app.state.engine = engine
    app.state.sessions = sessions

    @app.get("/test/organization-admin")
    def role_probe(
        membership: Annotated[
            OrganizationMembership, Depends(require_organization_role(Role.OWNER, Role.ADMIN))
        ],
    ):
        return {"role": membership.role.value}

    yield app


@pytest.fixture
def auth_client(identity_app):
    # Lifespan is covered separately by M1 tests. Auth tests use the isolated database above.
    client = TestClient(identity_app, headers={"Origin": "http://localhost:3000"})
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(scope="session")
def demo_mcp():
    """The real NexusFlow demo MCP server (apps/mcp-demo) over streamable HTTP."""
    from nexusflow_mcp_demo.server import create_app

    with serve(lambda host: create_app([host])) as live:
        yield live


@pytest.fixture
def mutable_mcp():
    server = build_mutable_server()
    with serve(lambda host: http_app(server, host)) as live:
        live.server = server
        yield live


@pytest.fixture
def closed_port():
    return free_port()


@pytest.fixture
def mcp_settings(demo_mcp, mutable_mcp, closed_port):
    # Explicit loopback allowlist, mirroring how Compose allowlists mcp-demo:8765.
    return {
        "mcp_allowed_hosts": [demo_mcp.host, mutable_mcp.host, f"127.0.0.1:{closed_port}"],
        "mcp_connect_timeout_seconds": 0.5,
        "mcp_request_timeout_seconds": 0.75,
    }


@pytest.fixture
def mcp_app(identity_app, mcp_settings):
    identity_app.state.settings = identity_app.state.settings.model_copy(update=mcp_settings)
    redis = MagicMock()
    redis.ping.return_value = True
    identity_app.state.redis = redis
    return identity_app
