from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.agent_teams import router as teams_router
from app.api.v1.agents import router as agents_router
from app.api.v1.approvals import router as approvals_router
from app.api.v1.auth import router as auth_router
from app.api.v1.evaluation import router as evaluation_router
from app.api.v1.health import router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.mcp_servers import router as mcp_router
from app.api.v1.memory import router as memory_router
from app.api.v1.observability import router as observability_router
from app.api.v1.organizations import router as organizations_router
from app.core.config import Settings, get_settings
from app.core.errors import install_error_handlers
from app.db.session import create_database
from app.jobs.queue import DramatiqQueue
from app.services.redis import create_redis


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine, sessions = create_database(settings)
        client = create_redis(settings)
        app.state.engine = engine
        app.state.sessions = sessions
        app.state.redis = client
        # Redis transport for job ids (M7). Connections are lazy: a Redis outage at startup
        # does not stop the API; sends fail fast and recovery re-delivers persisted jobs.
        app.state.queue = DramatiqQueue(settings) if settings.execution_mode == "queue" else None
        try:
            yield
        finally:
            if app.state.queue is not None:
                app.state.queue.close()
            client.close()
            engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Accept", "Content-Type", "Authorization", "X-Organization-ID"],
    )
    app.include_router(router, prefix=settings.api_v1_prefix)
    app.include_router(auth_router, prefix=settings.api_v1_prefix)
    app.include_router(organizations_router, prefix=settings.api_v1_prefix)
    app.include_router(agents_router, prefix=settings.api_v1_prefix)
    app.include_router(mcp_router, prefix=settings.api_v1_prefix)
    app.include_router(teams_router, prefix=settings.api_v1_prefix)
    app.include_router(approvals_router, prefix=settings.api_v1_prefix)
    app.include_router(memory_router, prefix=settings.api_v1_prefix)
    app.include_router(knowledge_router, prefix=settings.api_v1_prefix)
    app.include_router(observability_router, prefix=settings.api_v1_prefix)
    app.include_router(evaluation_router, prefix=settings.api_v1_prefix)
    install_error_handlers(app)
    return app
