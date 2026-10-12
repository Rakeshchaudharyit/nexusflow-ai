from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import APIError
from app.core.security import (
    hash_password,
    hash_refresh_token,
    issue_access_token,
    new_refresh_token,
    password_hasher,
    verify_password,
)
from app.models.identity import RefreshSession, User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest
from app.services.organizations import add_owned_organization, user_response


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def invalid_session() -> APIError:
    return APIError(401, "invalid_session", "Your session has expired. Please sign in again.")


def add_session(
    db: Session,
    user: User,
    settings: Settings,
    user_agent: str | None,
    previous: RefreshSession | None = None,
) -> tuple[RefreshSession, str]:
    raw = new_refresh_token()
    record = RefreshSession(
        user_id=user.id,
        token_hash=hash_refresh_token(raw),
        expires_at=previous.expires_at
        if previous
        else datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
        user_agent=user_agent[:512] if user_agent else None,
    )
    if previous:
        record.family_id = previous.family_id
    db.add(record)
    db.flush()
    return record, raw


def authenticated_result(
    db: Session, user: User, record: RefreshSession, settings: Settings
) -> AuthResponse:
    return AuthResponse(
        access_token=issue_access_token(user.id, record.family_id, settings),
        expires_in=settings.access_token_expire_minutes * 60,
        user=user_response(db, user),
    )


def register(db: Session, data: RegisterRequest, settings: Settings, user_agent: str | None):
    user = User(
        email=str(data.email),
        password_hash=hash_password(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        last_login_at=datetime.now(UTC),
    )
    try:
        db.add(user)
        db.flush()
        add_owned_organization(db, user, data.organization_name)
        record, raw = add_session(db, user, settings, user_agent)
        result = authenticated_result(db, user, record, settings)
        db.commit()
    except IntegrityError as error:
        db.rollback()
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_users_email" or "users.email" in str(error.orig):
            raise APIError(
                409, "email_in_use", "An account with this email already exists."
            ) from error
        raise
    return result, raw, record.expires_at


def login(db: Session, data: LoginRequest, settings: Settings, user_agent: str | None):
    user = db.scalar(select(User).where(User.email == str(data.email)))
    if (
        not verify_password(data.password, user.password_hash if user else None)
        or not user
        or not user.is_active
    ):
        raise APIError(401, "invalid_credentials", "Invalid email or password.")
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(data.password)
    user.last_login_at = datetime.now(UTC)
    record, raw = add_session(db, user, settings, user_agent)
    result = authenticated_result(db, user, record, settings)
    db.commit()
    return result, raw, record.expires_at


def find_cookie_session(db: Session, raw: str | None) -> RefreshSession:
    if not raw or len(raw) > 256:
        raise invalid_session()
    record = db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(raw))
    )
    if record is None:
        raise invalid_session()
    return record


def revoke_family(db: Session, record: RefreshSession):
    db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == record.user_id,
            RefreshSession.family_id == record.family_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


def refresh(db: Session, raw: str | None, settings: Settings, user_agent: str | None):
    record = find_cookie_session(db, raw)
    # Serialize rotations and logout for this user, including insertion of replacement sessions.
    user = db.scalar(select(User).where(User.id == record.user_id).with_for_update())
    record = db.scalar(
        select(RefreshSession)
        .where(RefreshSession.id == record.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if record.revoked_at is not None:
        revoke_family(db, record)
        db.commit()
        raise invalid_session()
    if utc(record.expires_at) <= datetime.now(UTC) or not user or not user.is_active:
        revoke_family(db, record)
        db.commit()
        raise invalid_session()
    record.revoked_at = datetime.now(UTC)
    record.last_used_at = record.revoked_at
    replacement, new_raw = add_session(db, user, settings, user_agent, record)
    result = authenticated_result(db, user, replacement, settings)
    db.commit()
    return result, new_raw, replacement.expires_at


def logout(db: Session, raw: str | None):
    if not raw or len(raw) > 256:
        return
    record = db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == hash_refresh_token(raw))
    )
    if record:
        db.scalar(select(User).where(User.id == record.user_id).with_for_update())
        revoke_family(db, record)
        db.commit()


def cookie_user(db: Session, raw: str | None) -> User:
    record = find_cookie_session(db, raw)
    user = db.get(User, record.user_id)
    if (
        record.revoked_at is not None
        or utc(record.expires_at) <= datetime.now(UTC)
        or not user
        or not user.is_active
    ):
        raise invalid_session()
    return user
