from fastapi import APIRouter, Request, Response

from app.schemas.health import HealthResponse, ReadinessResponse
from app.services.health import check_readiness

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(service=settings.app_name, version=settings.app_version)


@router.get("/health/ready", response_model=ReadinessResponse)
def readiness(request: Request, response: Response) -> ReadinessResponse:
    result = check_readiness(request.app.state.engine, request.app.state.redis)
    response.status_code = 200 if result.status == "ready" else 503
    response.headers["Cache-Control"] = "no-store"
    return result
