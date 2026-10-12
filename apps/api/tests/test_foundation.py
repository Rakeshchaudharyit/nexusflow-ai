from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def application():
    settings = Settings(_env_file=None, postgres_password="test-only-password", app_env="test")
    engine = MagicMock()
    redis = MagicMock()
    redis.ping.return_value = True
    with (
        patch("app.main.create_database", return_value=(engine, MagicMock())),
        patch("app.main.create_redis", return_value=redis),
        TestClient(create_app(settings)) as client,
    ):
        yield client, engine, redis
    engine.dispose.assert_called_once()
    redis.close.assert_called_once()


def test_health_is_independent_of_dependencies(application):
    client, engine, redis = application
    engine.connect.side_effect = RuntimeError("private database details")
    redis.ping.side_effect = RuntimeError("private redis details")
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "nexusflow-api", "version": "0.1.0"}
    engine.connect.assert_not_called()
    redis.ping.assert_not_called()


def test_readiness_checks_both_dependencies(application):
    client, engine, redis = application
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "services": {"api": "ok", "postgres": "ok", "redis": "ok"},
    }
    engine.connect.return_value.__enter__.return_value.execute.assert_called_once()
    redis.ping.assert_called_once()
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("failed", ["postgres", "redis", "both"])
def test_readiness_failure_is_safe_and_reports_each_service(application, failed):
    client, engine, redis = application
    if failed in ("postgres", "both"):
        engine.connect.side_effect = RuntimeError("secret database credentials")
    if failed in ("redis", "both"):
        redis.ping.side_effect = RuntimeError("secret redis credentials")
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "services": {
            "api": "ok",
            "postgres": "unavailable" if failed in ("postgres", "both") else "ok",
            "redis": "unavailable" if failed in ("redis", "both") else "ok",
        },
    }
    assert "secret" not in response.text
    redis.ping.assert_called_once()


def test_false_redis_ping_is_not_ready(application):
    client, _, redis = application
    redis.ping.return_value = False
    assert client.get("/api/v1/health/ready").status_code == 503


def test_cors_allows_only_configured_origin(application):
    client, _, _ = application
    allowed = client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
    denied = client.get("/api/v1/health", headers={"Origin": "https://untrusted.example"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers
    assert allowed.headers["access-control-allow-credentials"] == "true"


def test_configuration_reads_environment(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-only-password")
    monkeypatch.setenv("APP_NAME", "configured-api")
    monkeypatch.setenv("CORS_ORIGINS", '["http://localhost:3100"]')
    settings = Settings(_env_file=None)
    assert settings.app_name == "configured-api"
    assert settings.cors_origins == ["http://localhost:3100"]
    assert "test-only-password" not in repr(settings)


@pytest.mark.parametrize(
    "overrides",
    [
        {"postgres_password": None},
        {"debug": True, "app_env": "production"},
        {"cors_origins": ["*"]},
        {"api_v1_prefix": "api/v1"},
        {"database_url": "sqlite:///test.db"},
        {"redis_url": "https://example.com"},
        {"postgres_port": 0},
    ],
)
def test_invalid_configuration_fails_early(overrides):
    with pytest.raises((ValidationError, ValueError)):
        Settings(_env_file=None, **{"postgres_password": "test-only-password", **overrides})


def test_database_url_handles_special_password_characters():
    settings = Settings(_env_file=None, postgres_password="p@ss:/?#")
    assert settings.sqlalchemy_url.password == "p@ss:/?#"


def test_production_disables_interactive_docs():
    app = create_app(
        Settings(
            _env_file=None,
            postgres_password="production-test-password-unique",
            app_env="production",
            auth_cookie_secure=True,
            jwt_secret_key="Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4Yz5Aa6Bb7Cc8",
            cors_origins=["https://app.example.com"],
            frontend_url="https://app.example.com",
            allowed_hosts=["app.example.com", "api"],
            redis_url="redis://redis:6379/0",
            mcp_allowed_hosts=["mcp-demo:8765"],
            knowledge_upload_dir="/data/knowledge",
        )
    )
    assert app.docs_url is None
    assert app.openapi_url is None
    assert app.debug is False
