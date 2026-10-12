from redis import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        settings.redis_connection_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )
