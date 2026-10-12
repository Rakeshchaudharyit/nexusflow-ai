"""Ownership guards for opt-in demo lifecycle."""

import pytest

from app.demo.seed import MARKER, check_owned, identity, snapshot, verify_manifest
from app.models import Organization, OrganizationMembership, Role, User
from app.models.agents import Agent


def demo_org(db, monkeypatch):
    email = "demo-guard@example.com"
    monkeypatch.setenv("DEMO_OWNER_EMAIL", email)
    user = User(email=email, password_hash="unused-test-hash", first_name="Demo", last_name="Guard")
    db.add(user)
    db.flush()
    org = Organization(
        id=identity(email),
        name="Demo",
        slug=MARKER + identity(email).hex,
        created_by_user_id=user.id,
    )
    db.add(org)
    db.flush()
    db.add(OrganizationMembership(organization_id=org.id, user_id=user.id, role=Role.OWNER))
    db.commit()
    return org, user


def test_demo_identity_is_stable_and_email_scoped():
    assert identity("DEMO@example.com") == identity("demo@example.com")
    assert identity("demo@example.com") != identity("other@example.com")


def test_reset_rejects_ordinary_workspace_marker(identity_db, monkeypatch):
    _, sessions = identity_db
    with sessions() as db:
        org, user = demo_org(db, monkeypatch)
        org.slug = "ordinary-workspace"
        with pytest.raises(RuntimeError, match="marker mismatch"):
            check_owned(db, org, user.id)


def test_reset_rejects_untracked_user_resources(identity_db, monkeypatch):
    _, sessions = identity_db
    with sessions() as db:
        org, user = demo_org(db, monkeypatch)
        manifest = {"rows": snapshot(db, org.id)}
        verify_manifest(db, org.id, manifest)
        db.add(
            Agent(
                organization_id=org.id,
                name="User created",
                slug="user-created",
                description="",
                instructions="Keep this",
                created_by_user_id=user.id,
            )
        )
        db.commit()
        with pytest.raises(RuntimeError, match="Untracked data"):
            verify_manifest(db, org.id, manifest)


def test_reset_rejects_new_membership(identity_db, monkeypatch):
    _, sessions = identity_db
    with sessions() as db:
        org, user = demo_org(db, monkeypatch)
        check_owned(db, org, user.id)
        other = User(
            email="other-guard@example.com",
            password_hash="unused-test-hash",
            first_name="Other",
            last_name="Guard",
        )
        db.add(other)
        db.flush()
        db.add(OrganizationMembership(organization_id=org.id, user_id=other.id, role=Role.MEMBER))
        db.commit()
        with pytest.raises(RuntimeError, match="additional memberships"):
            check_owned(db, org, user.id)
