import logging

from redis import Redis
from sqlalchemy import Engine, text

from app.schemas.health import ReadinessResponse, ServiceStatus

logger = logging.getLogger(__name__)


def check_readiness(engine: Engine, redis: Redis) -> ReadinessResponse:
    postgres = "unavailable"
    redis_status = "unavailable"
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        postgres = "ok"
    except Exception:
        logger.warning("PostgreSQL readiness probe failed")
    try:
        if redis.ping():
            redis_status = "ok"
    except Exception:
        logger.warning("Redis readiness probe failed")
    ready = postgres == redis_status == "ok"
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        services=ServiceStatus(postgres=postgres, redis=redis_status),
    )
