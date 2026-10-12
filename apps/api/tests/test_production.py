"""M11 production configuration boundaries and privacy regression checks."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from app.observability.redact import clip

PRODUCTION = dict(
    _env_file=None,
    app_env="production",
    auth_cookie_secure=True,
    jwt_secret_key="Ab3Cd4Ef5Gh6Ij7Kl8Mn9Op0Qr1St2Uv3Wx4Yz5Aa6Bb7Cc8",
    postgres_password="production-test-password-unique",
    cors_origins=["https://app.example.com"],
    frontend_url="https://app.example.com",
    allowed_hosts=["app.example.com", "api"],
    redis_url="redis://redis:6379/0",
    mcp_allowed_hosts=["mcp-demo:8765"],
    knowledge_upload_dir="/data/knowledge",
)


@pytest.mark.parametrize(
    "overrides",
    [
        {"jwt_secret_key": "x" * 64},
        {"postgres_password": "weak"},
        {"cors_origins": ["http://app.example.com"]},
        {"allowed_hosts": ["*"]},
        {"redis_url": "redis://public.example.com:6379/0"},
        {"knowledge_upload_dir": ".data/knowledge"},
        {"knowledge_upload_dir": "/"},
        {"database_url": "postgresql+psycopg://user:long-secret-password@db.example.com/db"},
        {"auth_cookie_secure": False},
        {"execution_mode": "inline"},
        {"debug": True},
    ],
)
def test_production_rejects_unsafe_configuration(overrides):
    with pytest.raises(ValidationError):
        Settings(**(PRODUCTION | overrides))


def test_production_requires_explicit_environment():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            auth_cookie_secure=True,
            jwt_secret_key=PRODUCTION["jwt_secret_key"],
            postgres_password="long-enough-password",
        )


def test_production_hosts_and_docs():
    app = create_app(Settings(**PRODUCTION))
    client = TestClient(app)
    assert client.get("/api/v1/health", headers={"host": "evil.example.com"}).status_code == 400
    for route in ("/docs", "/openapi.json"):
        assert client.get(route, headers={"host": "app.example.com"}).status_code == 404


def test_trace_masks_entire_jwt():
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwcml2YXRlIn0.private-signature"
    value = clip(f"credential {token} end")
    assert value == "credential [redacted] end"


@pytest.mark.parametrize(
    "token",
    [
        "sk-proj-synthetic_provider_key_0123456789",
        "sk-synthetic_legacy_key_0123456789",
        "sk-svcacct-synthetic-service-key-0123456789",
    ],
)
def test_trace_masks_entire_provider_key(token):
    assert clip(f"credential {token} end") == "credential [redacted] end"
