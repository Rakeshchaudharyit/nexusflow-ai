from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import CurrentUser, Database, require_browser_origin
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserResponse
from app.services import auth
from app.services.organizations import user_response

router = APIRouter(prefix="/auth", tags=["authentication"])


def set_session_cookie(request: Request, response: Response, raw: str, expires_at: datetime):
    settings = request.app.state.settings
    expires_at = auth.utc(expires_at)
    response.set_cookie(
        settings.auth_cookie_name,
        raw,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
        path="/",
        expires=expires_at,
        max_age=max(0, int((expires_at - datetime.now(UTC)).total_seconds())),
    )
    response.headers["Cache-Control"] = "no-store"


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=201,
    dependencies=[Depends(require_browser_origin)],
)
def register(data: RegisterRequest, request: Request, response: Response, db: Database):
    result, raw, expires_at = auth.register(
        db, data, request.app.state.settings, request.headers.get("user-agent")
    )
    set_session_cookie(request, response, raw, expires_at)
    return result


@router.post("/login", response_model=AuthResponse, dependencies=[Depends(require_browser_origin)])
def login(data: LoginRequest, request: Request, response: Response, db: Database):
    result, raw, expires_at = auth.login(
        db, data, request.app.state.settings, request.headers.get("user-agent")
    )
    set_session_cookie(request, response, raw, expires_at)
    return result


@router.post(
    "/refresh", response_model=AuthResponse, dependencies=[Depends(require_browser_origin)]
)
def refresh(request: Request, response: Response, db: Database):
    result, raw, expires_at = auth.refresh(
        db,
        request.cookies.get(request.app.state.settings.auth_cookie_name),
        request.app.state.settings,
        request.headers.get("user-agent"),
    )
    set_session_cookie(request, response, raw, expires_at)
    return result


@router.post("/logout", status_code=204, dependencies=[Depends(require_browser_origin)])
def logout(request: Request, db: Database):
    settings = request.app.state.settings
    auth.logout(db, request.cookies.get(settings.auth_cookie_name))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
    return response


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser, db: Database, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return user_response(db, user)


@router.get("/session", response_model=UserResponse)
def session(request: Request, db: Database, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return user_response(
        db, auth.cookie_user(db, request.cookies.get(request.app.state.settings.auth_cookie_name))
    )
