"""Background worker (M7). Start with:

    dramatiq app.worker --processes 1 --threads 4

Each message carries only a job id. The worker claims the job in PostgreSQL, runs it through
the same AgentRuntime / TeamRuntime the API used before M7, and records the outcome. A
recovery loop in every worker process re-delivers lost messages and recovers stale jobs.
"""

import logging
import threading
import time
from pathlib import Path
from uuid import UUID

import dramatiq
from dramatiq.middleware import Middleware

from app.core.config import get_settings
from app.db.session import create_database
from app.evaluation.runner import EvaluationRunner
from app.jobs import runtimes
from app.jobs.executor import JobExecutor, new_worker_id
from app.jobs.queue import create_broker, declare_actor
from app.jobs.service import deliver, recover
from app.services.health import check_readiness
from app.services.redis import create_redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("nexusflow.worker")
# Touched by the recovery loop; the container healthcheck reads its age.
LIVENESS_FILE = Path("/tmp/nexusflow-worker-alive")

settings = get_settings()
broker = create_broker(settings)
dramatiq.set_broker(broker)

_lock = threading.Lock()
_executor: JobExecutor | None = None


class ActorQueue:
    """Worker-side transport for retries and recovery re-delivery."""

    def send(self, job_id: UUID, delay_seconds: float = 0) -> None:
        execute_job.send_with_options(args=(str(job_id),), delay=int(delay_seconds * 1000) or None)


def executor() -> JobExecutor:
    """Built lazily once per worker process (after Dramatiq forks), shared by its threads."""
    global _executor
    with _lock:
        if _executor is None:
            engine, sessions = create_database(settings)
            redis_client = create_redis(settings)
            tools = runtimes.internal_tools(
                lambda: check_readiness(engine, redis_client), sessions, settings
            )
            mcp = runtimes.mcp_client(settings)
            _executor = JobExecutor(
                sessions,
                settings,
                runtimes.agent_runtime(settings, sessions, tools, mcp),
                runtimes.team_runtime(settings, sessions, tools, mcp),
                queue=ActorQueue(),
                worker_id=new_worker_id(),
                knowledge=runtimes.knowledge_ingestor(settings, sessions),
            )
            # Evaluations execute their cases' runs through this same executor.
            _executor.evaluations = EvaluationRunner(sessions, settings, _executor.run)
            logger.info("Worker %s ready on queue %s", _executor.worker_id, settings.queue_name)
        return _executor


def run_job(job_id: str) -> None:
    executor().run(UUID(job_id))


execute_job = declare_actor(broker, settings, run_job)


def recover_once() -> None:
    worker = executor()
    report = recover(worker.sessions, settings)
    if report.requeued or report.failed or report.redeliver:
        logger.warning(
            "Recovery: requeued=%s failed=%s redelivering=%s",
            [str(i) for i in report.requeued],
            [str(i) for i in report.failed],
            len(report.redeliver),
        )
    with worker.sessions() as db:
        for job_id, delay in report.redeliver:
            deliver(db, worker.queue, job_id, delay)


class Recovery(Middleware):
    """Runs recovery at worker boot and every JOB_RECOVERY_SECONDS, without external cron.
    Safe to run in several workers at once: every transition is a locked, re-checked update."""

    def __init__(self):
        self._stop = threading.Event()

    def _loop(self) -> None:
        while True:
            try:
                recover_once()
                LIVENESS_FILE.touch()
            except Exception as error:
                logger.error("Recovery pass failed (%s); retrying later", type(error).__name__)
            if self._stop.wait(settings.job_recovery_seconds):
                return

    def after_worker_boot(self, broker, worker):
        threading.Thread(target=self._loop, name="job-recovery", daemon=True).start()

    def before_worker_shutdown(self, broker, worker):
        self._stop.set()


broker.add_middleware(Recovery())


def wait_for_liveness(max_age_seconds: float = 90) -> bool:  # used by the container healthcheck
    try:
        return time.time() - LIVENESS_FILE.stat().st_mtime < max_age_seconds
    except FileNotFoundError:
        return False
