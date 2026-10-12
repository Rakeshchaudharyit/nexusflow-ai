"""Executes an evaluation run inside the M7 worker (`evaluation_run` job).

For each case, in order:
  1. resolve the target (the case's own agent/team, else the run's);
  2. if the case has setup (inputs or memory), create an isolated evaluation thread owned by
     this evaluation run: user threads and user memory are never read or written;
  3. create a real run (agent or team, tagged with evaluation_run_id) and execute its job to
     completion through the same JobExecutor, so the real runtime, policy, approvals, retries
     and tracing all apply;
  4. observe the persisted outcome and apply the deterministic checks;
  5. store one EvaluationResult (unique per run and case) and commit.

A failed expectation is a completed result, never a job failure. A case that cannot execute
is an `error` result and the remaining cases continue. If the job itself is retried after an
infrastructure fault, cases that already have results are skipped, so nothing is duplicated.
Approval-required runs are left unexecuted and then cancelled: evaluations never approve.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.agents.errors import AgentRuntimeError
from app.core.config import Settings
from app.evaluation.checks import Observation, run_checks, score
from app.evaluation.config import snapshot
from app.jobs import cancel as cancellation
from app.jobs.control import JobCancelled, JobControl, JobLost
from app.models.agents import RunStatus
from app.models.approvals import ActionExecution
from app.models.evaluation import (
    CaseTarget,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    EvaluationRunStatus,
    ResultStatus,
)
from app.models.identity import Role, User
from app.models.jobs import ExecutionJob, JobStatus
from app.models.knowledge import KnowledgeChunk
from app.models.memory import MemoryEntry, MemoryScope, MemorySource, MemoryThread, MemoryType
from app.services import agent_teams, agents

logger = logging.getLogger(__name__)
TERMINAL_JOB = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
CASE_TIMEOUT_SECONDS = 180


class CaseError(Exception):
    """The case could not be executed (recorded as an `error` result)."""


class NoQueue:
    """Child runs are executed by this worker directly, not handed to Redis."""

    def send(self, job_id: UUID, delay_seconds: float = 0) -> None:
        return None


def now() -> datetime:
    return datetime.now(UTC)


class EvaluationRunner:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        settings: Settings,
        run_job: Callable[[UUID], object],
    ):
        self._sessions = sessions
        self._settings = settings
        self._run_job = run_job

    # --- lifecycle --------------------------------------------------------------------------

    def execute(self, evaluation_run_id: UUID, control: JobControl) -> None:
        started = time.perf_counter()
        with self._sessions() as db:
            run = db.get(EvaluationRun, evaluation_run_id, with_for_update=True)
            if run is None or run.status not in (
                EvaluationRunStatus.QUEUED,
                EvaluationRunStatus.RUNNING,
            ):
                raise AgentRuntimeError(
                    "The evaluation run is not waiting to execute.", code="evaluation_not_queued"
                )
            organization_id = run.organization_id
            cases = list(
                db.scalars(
                    select(EvaluationCase)
                    .where(
                        EvaluationCase.dataset_id == run.dataset_id,
                        EvaluationCase.organization_id == organization_id,
                    )
                    .order_by(EvaluationCase.position, EvaluationCase.created_at, EvaluationCase.id)
                )
            )
            agent_ids = {run.target_agent_id} | {c.target_agent_id for c in cases}
            team_ids = {run.target_team_id} | {c.target_team_id for c in cases}
            data, digest = snapshot(
                db,
                self._settings,
                organization_id,
                {item for item in agent_ids if item},
                {item for item in team_ids if item},
            )
            run.status = EvaluationRunStatus.RUNNING
            run.started_at = run.started_at or now()
            run.case_count = len(cases)
            run.target_snapshot, run.config_hash = data, digest
            target = SimpleNamespace(
                agent_id=run.target_agent_id,
                team_id=run.target_team_id,
                user=db.get(User, run.created_by_user_id),
            )
            done = set(
                db.scalars(
                    select(EvaluationResult.case_id).where(
                        EvaluationResult.evaluation_run_id == run.id
                    )
                )
            )
            db.commit()
        try:
            for case in cases:
                if case.id in done:
                    continue  # a retried job resumes after the cases already evaluated
                control.checkpoint()
                self._evaluate_case(evaluation_run_id, organization_id, case, target)
            control.checkpoint()
        except JobCancelled:
            self._finish(control, evaluation_run_id, started, EvaluationRunStatus.CANCELLED)
            return
        except JobLost:
            logger.warning("Evaluation %s: attempt lost its job; stopping", evaluation_run_id)
            return
        self._finish(control, evaluation_run_id, started, EvaluationRunStatus.COMPLETED)

    def _finish(self, control, evaluation_run_id, started, status) -> None:
        with self._sessions() as db:
            run = db.get(EvaluationRun, evaluation_run_id, with_for_update=True)
            control.settle(
                db, "cancelled" if status == EvaluationRunStatus.CANCELLED else "completed"
            )
            results = list(
                db.scalars(
                    select(EvaluationResult).where(EvaluationResult.evaluation_run_id == run.id)
                )
            )
            run.passed_count = sum(1 for item in results if item.status == ResultStatus.PASSED)
            run.failed_count = sum(1 for item in results if item.status == ResultStatus.FAILED)
            run.error_count = sum(1 for item in results if item.status == ResultStatus.ERROR)
            run.score = (
                round(sum(item.score for item in results) / len(results), 4) if results else None
            )
            run.status = status
            run.completed_at = now()
            run.duration_ms = round((time.perf_counter() - started) * 1000)
            db.commit()

    # --- one case ---------------------------------------------------------------------------

    def _evaluate_case(self, evaluation_run_id, organization_id, case, target) -> None:
        started = time.perf_counter()
        run_type = run_id = None
        try:
            kind = case.target_kind
            agent_id = case.target_agent_id or target.agent_id
            team_id = case.target_team_id or target.team_id
            if kind == CaseTarget.AGENT and agent_id is None:
                raise CaseError("No target agent is configured for this agent case.")
            if kind == CaseTarget.TEAM and team_id is None:
                raise CaseError("No target team is configured for this team case.")
            thread_id = None
            if case.setup_inputs or case.setup_memory:
                thread_id = self._thread(evaluation_run_id, organization_id, case, target.user)
            for text in case.setup_inputs or []:
                self._run(
                    kind,
                    organization_id,
                    target.user,
                    agent_id,
                    team_id,
                    text,
                    thread_id,
                    evaluation_run_id,
                )
            run_type, run_id = self._run(
                kind,
                organization_id,
                target.user,
                agent_id,
                team_id,
                case.input_text,
                thread_id,
                evaluation_run_id,
            )
            observed = self._observe(organization_id, run_type, run_id)
            checks, metrics = run_checks(case, observed)
            if not checks:
                checks = [
                    {"name": "has_expectations", "passed": False, "expected": ">= 1", "actual": 0}
                ]
            passed = all(item["passed"] for item in checks)
            reasons = [
                f"{item['name']}: expected {item['expected']!r}, got {item['actual']!r}"
                for item in checks
                if not item["passed"]
            ]
            actual = {**observed.summary(), **({"retrieval": metrics} if metrics else {})}
            result = dict(
                status=ResultStatus.PASSED if passed else ResultStatus.FAILED,
                passed=passed,
                score=score(checks),
                checks_json=checks,
                failure_reasons=reasons[:20],
                actual_json=actual,
            )
            if observed.status == RunStatus.AWAITING_APPROVAL.value:
                self._cancel_pending(organization_id, run_id, target.user)
        except (CaseError, AgentRuntimeError) as error:
            message = getattr(error, "message", None) or str(error)
            result = dict(
                status=ResultStatus.ERROR,
                passed=False,
                score=0.0,
                checks_json=[],
                failure_reasons=[message[:300]],
                actual_json={},
            )
        with self._sessions() as db:
            db.add(
                EvaluationResult(
                    organization_id=organization_id,
                    evaluation_run_id=evaluation_run_id,
                    case_id=case.id,
                    actual_run_type=run_type,
                    actual_run_id=run_id,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    created_at=now(),
                    **result,
                )
            )
            db.commit()

    def _thread(self, evaluation_run_id, organization_id, case, user) -> UUID:
        """An isolated thread for this case, owned by the evaluation run (hidden from users)."""
        with self._sessions() as db:
            thread = MemoryThread(
                organization_id=organization_id,
                created_by_user_id=user.id,
                title=f"Evaluation · {case.name}"[:200],
                evaluation_run_id=evaluation_run_id,
            )
            db.add(thread)
            db.flush()
            for index, note in enumerate(case.setup_memory or []):
                db.add(
                    MemoryEntry(
                        organization_id=organization_id,
                        memory_type=MemoryType.THREAD,
                        scope=MemoryScope.THREAD,
                        thread_id=thread.id,
                        content=str(note)[:2000],
                        summary=str(note)[:500],
                        source_type=MemorySource.MANUAL,
                        created_by_user_id=user.id,
                        idempotency_key=f"evaluation:{thread.id}:setup:{index}",
                    )
                )
            db.commit()
            return thread.id

    def _run(
        self, kind, organization_id, user, agent_id, team_id, text, thread_id, evaluation_run_id
    ):
        with self._sessions() as db:
            try:
                if kind == CaseTarget.AGENT:
                    created = agents.run_agent(
                        db,
                        NoQueue(),
                        self._settings,
                        organization_id,
                        user,
                        agent_id,
                        text,
                        thread_id,
                        evaluation_run_id,
                    )
                    run_type = "agent"
                else:
                    created = agent_teams.run_team(
                        db,
                        NoQueue(),
                        self._settings,
                        organization_id,
                        user,
                        team_id,
                        text,
                        thread_id,
                        evaluation_run_id,
                    )
                    run_type = "team"
            except Exception as error:  # e.g. target not active (APIError)
                detail = getattr(error, "detail", None)
                message = detail.get("message") if isinstance(detail, dict) else str(error)
                raise CaseError(message or "The run could not be created.") from error
            run_id = created.run_id
            column = ExecutionJob.agent_run_id if run_type == "agent" else ExecutionJob.team_run_id
            job_id = db.scalar(
                select(ExecutionJob.id).where(
                    column == run_id, ExecutionJob.organization_id == organization_id
                )
            )
        self._complete(job_id)
        return run_type, run_id

    def _complete(self, job_id: UUID) -> None:
        """Run the child job through the executor until it settles (bounded wait)."""
        deadline = time.monotonic() + CASE_TIMEOUT_SECONDS
        while True:
            self._run_job(job_id)
            with self._sessions() as db:
                job = db.get(ExecutionJob, job_id)
                status, next_retry_at = job.status, job.next_retry_at
            if status in TERMINAL_JOB:
                return
            if time.monotonic() > deadline:
                raise CaseError("The case run did not finish in time.")
            wait = 0.2
            if status == JobStatus.RETRYING and next_retry_at is not None:
                if next_retry_at.tzinfo is None:
                    next_retry_at = next_retry_at.replace(tzinfo=UTC)
                wait = min(max((next_retry_at - now()).total_seconds(), 0.0), 5.0)
            time.sleep(wait)

    def _cancel_pending(self, organization_id, run_id, user) -> None:
        """Evaluations never approve: a run paused for approval is cancelled after checking."""
        membership = SimpleNamespace(
            organization_id=organization_id, user_id=user.id, role=Role.OWNER
        )
        with self._sessions() as db:
            try:
                cancellation.cancel_team_run(db, membership, run_id)
            except Exception as error:
                logger.warning("Could not cancel evaluation approval run %s (%s)", run_id, error)
                db.rollback()

    # --- observation ------------------------------------------------------------------------

    def _observe(self, organization_id: UUID, run_type: str, run_id: UUID) -> Observation:
        with self._sessions() as db:
            if run_type == "agent":
                detail = agents.get_run(db, organization_id, run_id)
                output = detail.final_output or {}
                knowledge = detail.knowledge or {}
                observed = Observation(
                    kind="agent",
                    status=detail.status.value,
                    text=output.get("summary") or "",
                    intent=output.get("intent") or (detail.state or {}).get("intent"),
                    tools=list(output.get("tools_used") or [c.tool_key for c in detail.tool_calls]),
                    final_output=output,
                    citations=list(output.get("citations") or []),
                    retrieved=list(knowledge.get("results") or []),
                    error_code=detail.error.code if detail.error else None,
                )
            else:
                detail = agent_teams.get_team_run(db, organization_id, run_id)
                output = detail.final_output or {}
                action = detail.action or {}
                tools = [
                    call.get("tool_key")
                    for result in detail.results
                    for call in result.tool_calls
                    if call.get("tool_key")
                ]
                retrieved = [
                    item
                    for result in detail.results
                    for item in ((result.output or {}).get("knowledge") or {}).get("results", [])
                ]
                text_parts = [output.get("summary") or ""] + list(output.get("key_findings") or [])
                observed = Observation(
                    kind="team",
                    status=detail.status.value,
                    text=" ".join(str(part) for part in text_parts),
                    tools=tools,
                    final_output=output,
                    citations=list(output.get("citations") or []),
                    retrieved=retrieved,
                    policy_decision=action.get("decision")
                    or ("none" if detail.final_output else None),
                    action_type=action.get("action_type"),
                    executions=db.scalar(
                        select(func.count())
                        .select_from(ActionExecution)
                        .where(
                            ActionExecution.team_run_id == run_id,
                            ActionExecution.organization_id == organization_id,
                        )
                    )
                    or 0,
                    error_code=detail.error.code if detail.error else None,
                )
                if detail.error and detail.error.code == "policy_denied" and not action:
                    observed.policy_decision = "deny"
            chunk_ids = {c.get("chunk_id") for c in observed.citations if c.get("chunk_id")}
            if chunk_ids:
                observed.existing_chunks = {
                    str(chunk_id)
                    for chunk_id in db.scalars(
                        select(KnowledgeChunk.id).where(
                            KnowledgeChunk.organization_id == organization_id,
                            KnowledgeChunk.id.in_([UUID(str(item)) for item in chunk_ids]),
                        )
                    )
                }
            return observed
