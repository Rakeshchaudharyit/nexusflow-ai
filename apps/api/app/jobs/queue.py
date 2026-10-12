"""Queue transports. Messages carry one job id and nothing else: no tokens, prompts or secrets.
The worker reloads everything it needs from PostgreSQL."""

from collections.abc import Callable
from uuid import UUID

import dramatiq
import redis
from dramatiq.brokers.redis import RedisBroker

from app.core.config import Settings

ACTOR_NAME = "execute_job"
# Generous ceiling for one attempt; heartbeats and recovery, not this, handle dead workers.
ACTOR_TIME_LIMIT_MS = 30 * 60 * 1000


def create_broker(settings: Settings) -> RedisBroker:
    # Short socket timeouts: a Redis outage must fail a send fast, never hang an API request.
    client = redis.Redis.from_url(
        settings.redis_connection_url, socket_connect_timeout=2, socket_timeout=5
    )
    return RedisBroker(client=client, namespace="nexusflow")


def declare_actor(
    broker: dramatiq.Broker, settings: Settings, fn: Callable[[str], None]
) -> dramatiq.Actor:
    # Dramatiq's own retries are disabled: retry policy lives in PostgreSQL (ExecutionJob).
    return dramatiq.actor(
        fn,
        actor_name=ACTOR_NAME,
        queue_name=settings.queue_name,
        broker=broker,
        max_retries=0,
        time_limit=ACTOR_TIME_LIMIT_MS,
    )


def _enqueue_only(job_id: str) -> None:  # pragma: no cover - executed by the worker module
    raise RuntimeError("The API process never executes jobs.")


class DramatiqQueue:
    """Used by the API to hand job ids to Redis."""

    def __init__(self, settings: Settings, broker: dramatiq.Broker | None = None):
        self.broker = broker or create_broker(settings)
        self._actor = declare_actor(self.broker, settings, _enqueue_only)

    def send(self, job_id: UUID, delay_seconds: float = 0) -> None:
        delay = int(delay_seconds * 1000) or None
        self._actor.send_with_options(args=(str(job_id),), delay=delay)

    def close(self) -> None:
        self.broker.close()


class InlineQueue:
    """Test/dev transport: executes the job immediately through the same JobExecutor."""

    def __init__(self, run: Callable[[UUID], object]):
        self._run = run

    def send(self, job_id: UUID, delay_seconds: float = 0) -> None:
        self._run(job_id)
