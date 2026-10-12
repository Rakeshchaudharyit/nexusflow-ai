from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.errors import APIError
from app.core.security import hash_refresh_token, verify_password
from app.models.identity import Organization, OrganizationMembership, RefreshSession, Role, User
from app.schemas.auth import LoginRequest
from app.services import auth

PASSWORD = "correct-horse-battery-staple"
COOKIE = "nexusflow_refresh"


def register(client, email="owner@example.com", organization="Cortexa Automation"):
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "first_name": "Rakesh",
            "last_name": "Chaudhary",
            "organization_name": organization,
        },
    )


def authorization(result):
    return {"Authorization": "Bearer " + result.json()["access_token"]}


def test_registration_creates_owner_and_sanitized_session(auth_client, identity_db):
    response = register(auth_client, " OWNER@EXAMPLE.COM ")
    assert response.status_code == 201
    data = response.json()
    assert data["user"]["email"] == "owner@example.com"
    assert data["user"]["is_verified"] is False
    assert data["user"]["organizations"][0]["role"] == "owner"
    assert "password" not in response.text
    assert "token_hash" not in response.text
    raw = auth_client.cookies.get(COOKIE)
    with identity_db[1]() as db:
        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD != user.password_hash
        assert verify_password(
            LoginRequest(email=user.email, password=PASSWORD).password, user.password_hash
        )
        record = db.scalar(select(RefreshSession))
        assert record.token_hash == hash_refresh_token(raw)
        assert record.token_hash != raw
        assert db.scalar(select(OrganizationMembership)).role == Role.OWNER
        assert db.scalar(select(Organization)).name == "Cortexa Automation"


def test_cookie_flags_and_no_cache(auth_client):
    response = register(auth_client)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Secure" not in cookie
    assert response.headers["cache-control"] == "no-store"
    assert "refresh_token" not in response.json()


def test_duplicate_registration_is_atomic(auth_client, identity_db):
    assert register(auth_client).status_code == 201
    assert register(auth_client, "OWNER@example.com").status_code == 409
    with identity_db[1]() as db:
        for model in [User, Organization, OrganizationMembership, RefreshSession]:
            assert db.scalar(select(func.count()).select_from(model)) == 1


def test_registration_rolls_back_when_workspace_creation_fails(auth_client, identity_db):
    with patch(
        "app.services.auth.add_owned_organization", side_effect=RuntimeError("internal-secret")
    ):
        with pytest.raises(RuntimeError):
            register(auth_client)
    with identity_db[1]() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(RefreshSession)) == 0


@pytest.mark.parametrize(
    "field,value",
    [("password", "short"), ("email", "invalid"), ("first_name", " "), ("organization_name", " ")],
)
def test_registration_validation_does_not_echo_sensitive_input(auth_client, field, value):
    data = {
        "email": "owner@example.com",
        "password": PASSWORD,
        "first_name": "Rakesh",
        "last_name": "Chaudhary",
        "organization_name": "Workspace",
    }
    data[field] = value
    response = auth_client.post("/api/v1/auth/register", json=data)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert PASSWORD not in response.text
    assert '"input"' not in response.text


def test_login_success_updates_last_login(auth_client, identity_db):
    register(auth_client)
    response = auth_client.post(
        "/api/v1/auth/login", json={"email": " OWNER@EXAMPLE.COM ", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert auth_client.get("/api/v1/auth/me", headers=authorization(response)).status_code == 200
    with identity_db[1]() as db:
        assert db.scalar(select(User)).last_login_at is not None
        assert db.scalar(select(func.count()).select_from(RefreshSession)) == 2


def test_invalid_login_does_not_disclose_account_existence(auth_client):
    register(auth_client)
    bad_password = auth_client.post(
        "/api/v1/auth/login", json={"email": "owner@example.com", "password": "incorrect"}
    )
    missing_user = auth_client.post(
        "/api/v1/auth/login", json={"email": "unknown@example.com", "password": "incorrect"}
    )
    assert bad_password.status_code == missing_user.status_code == 401
    assert bad_password.json() == missing_user.json()


def test_me_requires_bearer_even_with_refresh_cookie(auth_client):
    register(auth_client)
    assert auth_client.get("/api/v1/auth/me").status_code == 401


def test_me_sanitizes_user(auth_client):
    response = register(auth_client)
    me = auth_client.get("/api/v1/auth/me", headers=authorization(response))
    assert me.status_code == 200
    assert me.json() == response.json()["user"]
    assert "hash" not in me.text


def test_refresh_rotates_and_preserves_absolute_expiry(auth_client, identity_db):
    result = register(auth_client)
    old_raw = auth_client.cookies.get(COOKIE)
    response = auth_client.post("/api/v1/auth/refresh")
    assert response.status_code == 200
    assert auth_client.cookies.get(COOKIE) != old_raw
    assert auth_client.get("/api/v1/auth/me", headers=authorization(response)).status_code == 200
    assert auth_client.get("/api/v1/auth/me", headers=authorization(result)).status_code == 200
    with identity_db[1]() as db:
        records = list(
            db.scalars(
                select(RefreshSession).order_by(RefreshSession.created_at, RefreshSession.id)
            )
        )
        old = next(item for item in records if item.token_hash == hash_refresh_token(old_raw))
        new = next(item for item in records if item.token_hash != old.token_hash)
        assert old.revoked_at and old.last_used_at
        assert old.family_id == new.family_id
        assert old.expires_at == new.expires_at


def test_replay_revokes_the_session_family(auth_client):
    register(auth_client)
    old = auth_client.cookies.get(COOKIE)
    rotated = auth_client.post("/api/v1/auth/refresh")
    current = auth_client.cookies.get(COOKIE)
    auth_client.cookies.clear()
    auth_client.cookies.set(COOKIE, old)
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401
    auth_client.cookies.clear()
    auth_client.cookies.set(COOKIE, current)
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401
    assert auth_client.get("/api/v1/auth/me", headers=authorization(rotated)).status_code == 401


def test_logout_is_idempotent_and_revokes_access(auth_client):
    registered = register(auth_client)
    raw = auth_client.cookies.get(COOKIE)
    assert auth_client.post("/api/v1/auth/logout").status_code == 204
    assert auth_client.cookies.get(COOKIE) is None
    assert auth_client.get("/api/v1/auth/me", headers=authorization(registered)).status_code == 401
    auth_client.cookies.set(COOKIE, raw)
    assert auth_client.post("/api/v1/auth/logout").status_code == 204
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_does_not_revoke_another_login_family(auth_client):
    first = register(auth_client)
    second = auth_client.post(
        "/api/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )
    auth_client.post("/api/v1/auth/logout")
    assert auth_client.get("/api/v1/auth/me", headers=authorization(first)).status_code == 200
    assert auth_client.get("/api/v1/auth/me", headers=authorization(second)).status_code == 401


@pytest.mark.parametrize("path", ["register", "login", "refresh", "logout"])
def test_cookie_mutations_reject_untrusted_origin(auth_client, path):
    response = auth_client.post(
        "/api/v1/auth/" + path, headers={"Origin": "https://evil.example"}, json={}
    )
    assert response.status_code == 403


def test_missing_origin_rejected(auth_client):
    assert auth_client.post("/api/v1/auth/refresh", headers={"Origin": ""}).status_code == 403


def test_expired_refresh_rejected(auth_client, identity_db):
    register(auth_client)
    with identity_db[1]() as db:
        db.scalar(select(RefreshSession)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401


def test_invalid_cookie_and_missing_cookie_rejected(auth_client):
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401
    auth_client.cookies.set(COOKIE, "not-a-valid-token")
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401


def test_inactive_user_cannot_login_refresh_or_access(auth_client, identity_db):
    registered = register(auth_client)
    with identity_db[1]() as db:
        db.scalar(select(User)).is_active = False
        db.commit()
    assert (
        auth_client.post(
            "/api/v1/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert auth_client.get("/api/v1/auth/me", headers=authorization(registered)).status_code == 401
    assert auth_client.get("/api/v1/auth/session").status_code == 401
    assert auth_client.post("/api/v1/auth/refresh").status_code == 401


def test_session_lookup_does_not_rotate_tokens(auth_client, identity_db):
    registered = register(auth_client)
    cookie = auth_client.cookies.get(COOKIE)
    response = auth_client.get("/api/v1/auth/session")
    assert response.status_code == 200
    assert response.json() == registered.json()["user"]
    assert auth_client.cookies.get(COOKIE) == cookie
    with identity_db[1]() as db:
        assert db.scalar(select(func.count()).select_from(RefreshSession)) == 1


@pytest.mark.parametrize(
    "change", ["expired", "type", "signature", "audience", "issuer", "missing", "subject"]
)
def test_jwt_validation_rejects_invalid_claims(auth_client, identity_app, change):
    result = register(auth_client)
    settings = identity_app.state.settings
    secret = settings.jwt_secret_key.get_secret_value()
    claims = jwt.decode(
        result.json()["access_token"],
        secret,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
    )
    if change == "expired":
        claims["exp"] = int((datetime.now(UTC) - timedelta(seconds=2)).timestamp())
    if change == "type":
        claims["type"] = "refresh"
    if change == "audience":
        claims["aud"] = "another-service"
    if change == "issuer":
        claims["iss"] = "another-service"
    if change == "missing":
        del claims["exp"]
    if change == "subject":
        claims["sub"] = "invalid-uuid"
    token = jwt.encode(
        claims,
        secret if change != "signature" else "different-signing-key-more-than-32-bytes",
        algorithm="HS256",
    )
    assert (
        auth_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + token}).status_code
        == 401
    )


def test_tenant_isolation_in_both_directions(auth_client):
    a = register(auth_client, "user-a@example.com", "Organization A")
    b = register(auth_client, "user-b@example.com", "Organization B")
    a_org = a.json()["user"]["organizations"][0]["id"]
    b_org = b.json()["user"]["organizations"][0]["id"]
    for own, other, token in [(a_org, b_org, authorization(a)), (b_org, a_org, authorization(b))]:
        assert auth_client.get(f"/api/v1/organizations/{own}", headers=token).status_code == 200
        assert auth_client.get(f"/api/v1/organizations/{other}", headers=token).status_code == 404
        assert (
            auth_client.get(
                "/api/v1/organizations/current", headers={**token, "X-Organization-ID": other}
            ).status_code
            == 404
        )
        listing = auth_client.get("/api/v1/organizations", headers=token).json()
        assert [org["id"] for org in listing] == [own]
        assert auth_client.get(f"/api/v1/organizations/{uuid4()}", headers=token).status_code == 404


def test_multiple_workspaces_have_unique_slugs_and_switch_context(auth_client):
    result = register(auth_client)
    headers = authorization(result)
    created = auth_client.post(
        "/api/v1/organizations", headers=headers, json={"name": "Cortexa Automation"}
    )
    assert created.status_code == 201
    assert created.json()["role"] == "owner"
    first = result.json()["user"]["organizations"][0]
    assert first["slug"] != created.json()["slug"]
    listing = auth_client.get("/api/v1/organizations", headers=headers).json()
    assert len(listing) == 2
    for organization in listing:
        response = auth_client.get(
            "/api/v1/organizations/current",
            headers={**headers, "X-Organization-ID": organization["id"]},
        )
        assert response.status_code == 200
        assert response.json()["id"] == organization["id"]


@pytest.mark.parametrize(
    "role,expected", [(Role.OWNER, 200), (Role.ADMIN, 200), (Role.MEMBER, 403)]
)
def test_roles_are_resolved_from_database(auth_client, identity_db, role, expected):
    result = register(auth_client)
    org = result.json()["user"]["organizations"][0]["id"]
    with identity_db[1]() as db:
        db.scalar(select(OrganizationMembership)).role = role
        db.commit()
    assert (
        auth_client.get(
            "/test/organization-admin", headers={**authorization(result), "X-Organization-ID": org}
        ).status_code
        == expected
    )


def test_removed_membership_invalidates_existing_access(auth_client, identity_db):
    result = register(auth_client)
    org = result.json()["user"]["organizations"][0]["id"]
    with identity_db[1]() as db:
        db.delete(db.scalar(select(OrganizationMembership)))
        db.commit()
    assert (
        auth_client.get(f"/api/v1/organizations/{org}", headers=authorization(result)).status_code
        == 404
    )
    assert (
        auth_client.get("/api/v1/auth/me", headers=authorization(result)).json()["organizations"]
        == []
    )


def test_tenant_header_must_be_valid_uuid(auth_client):
    result = register(auth_client)
    assert (
        auth_client.get(
            "/api/v1/organizations/current",
            headers={**authorization(result), "X-Organization-ID": "invalid"},
        ).status_code
        == 422
    )
    assert (
        auth_client.get("/api/v1/organizations/current", headers=authorization(result)).status_code
        == 422
    )


def test_organizations_require_authentication(auth_client):
    assert auth_client.get("/api/v1/organizations").status_code == 401
    assert auth_client.post("/api/v1/organizations", json={"name": "Other"}).status_code == 401


def test_membership_unique_constraint(auth_client, identity_db):
    register(auth_client)
    with identity_db[1]() as db:
        membership = db.scalar(select(OrganizationMembership))
        db.add(
            OrganizationMembership(
                organization_id=membership.organization_id,
                user_id=membership.user_id,
                role=Role.MEMBER,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"jwt_secret_key": "short"},
        {"jwt_algorithm": "none"},
        {"app_env": "production", "auth_cookie_secure": False},
        {"auth_cookie_samesite": "none", "auth_cookie_secure": False},
        {"access_token_expire_minutes": 0},
        {"refresh_token_expire_days": 0},
    ],
)
def test_auth_configuration_rejects_unsafe_values(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{"postgres_password": "test", **overrides})


def test_production_cookie_is_secure(auth_client, identity_app):
    identity_app.state.settings.auth_cookie_secure = True
    assert "Secure" in register(auth_client).headers["set-cookie"]


def test_concurrent_refresh_on_postgres_revokes_replayed_family(
    auth_client, identity_db, identity_app
):
    if identity_db[0].dialect.name != "postgresql":
        pytest.skip("PostgreSQL is required to verify row-lock concurrency")
    register(auth_client)
    raw = auth_client.cookies.get(COOKIE)
    barrier = Barrier(2)

    def rotate():
        barrier.wait(timeout=10)
        with identity_db[1]() as db:
            try:
                result, _, _ = auth.refresh(db, raw, identity_app.state.settings, None)
                return result.access_token
            except APIError as error:
                assert error.status_code == 401
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rotate(), range(2)))
    tokens = [token for token in results if token]
    assert len(tokens) == 1
    assert (
        auth_client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer " + tokens[0]}
        ).status_code
        == 401
    )
    with identity_db[1]() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(RefreshSession)
                .where(RefreshSession.revoked_at.is_(None))
            )
            == 0
        )
