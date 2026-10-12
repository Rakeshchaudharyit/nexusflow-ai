from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.agents.errors import AgentExecutionError, AgentRuntimeError
from app.agents.events import EventStream
from app.agents.state import AgentState, RunError, RunStateSnapshot
from app.core.config import Settings
from app.jobs.control import JobControl
from app.knowledge.access import granted_sources
from app.memory.writer import remember_agent_result
from app.models.agents import (
    Agent,
    AgentRun,
    AgentStatus,
    RunEventStatus,
    RunEventType,
    RunStatus,
)
from app.models.observability import SpanStatus, SpanType
from app.observability.tracer import Tracer, keys, node_metadata

INTERNAL_NODE_ERROR = "The step failed unexpectedly."
NODE_LABELS = {
    "analyze_request": "Analyze request",
    "create_plan": "Create plan",
    "execute_demo_tool": "Execute tool",
    "compose_response": "Compose response",
}


@dataclass(frozen=True)
class RunJob:
    run_id: UUID
    organization_id: UUID
    agent_id: UUID
    user_id: UUID
    input_text: str
    instructions: str
    thread_id: UUID | None = None
    workspace_memory_enabled: bool = False
    # M9: sources this agent may search (empty without the knowledge_search tool grant).
    knowledge_source_ids: tuple[UUID, ...] = ()


def safe_error(error: BaseException) -> tuple[str, str, dict[str, Any]]:
    if isinstance(error, AgentRuntimeError):
        return error.code, error.message, error.details
    return "internal_error", INTERNAL_NODE_ERROR, {}


class RunRecorder:
    """Persists one run's lifecycle using a short transaction per write.

    The sequence counter lives on this per-run instance, so events are numbered 1..n in
    the order they are recorded; uq_agent_run_events_run_sequence rejects any duplicate.
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        run_id: UUID,
        control: JobControl | None = None,
        memory_settings: Settings | None = None,
        tracer: Tracer | None = None,
    ):
        self._sessions = sessions
        self._run_id = run_id
        self._control = control
        # M10: observational spans for each graph node (never part of the business record).
        self._tracer = tracer
        self._node_spans: dict[str, Any] = {}
        # M8: when set, a completed run in a thread writes its validated facts to memory.
        self._memory_settings = memory_settings
        self._thread_id: UUID | None = None
        self._user_id: UUID | None = None
        self._events = EventStream(sessions, run_id=run_id)
        self._steps = 0
        self._started = perf_counter()
        self.failed_node: str | None = None

    @property
    def claimed(self) -> bool:
        return self._events.organization_id is not None

    def _duration(self) -> int:
        return round((perf_counter() - self._started) * 1000)

    def start(self) -> RunJob:
        """Move a queued run to running. Raises when the run cannot execute."""
        with self._sessions() as db:
            run = db.scalar(select(AgentRun).where(AgentRun.id == self._run_id).with_for_update())
            if run is None or run.status != RunStatus.QUEUED:
                raise AgentExecutionError(
                    "The run is not waiting to execute.", code="run_not_queued"
                )
            agent = db.scalar(
                select(Agent).where(
                    Agent.id == run.agent_id, Agent.organization_id == run.organization_id
                )
            )
            # Continue numbering after earlier attempts; the run lock serialises writers.
            self._events.resume(db, run.organization_id)
            if self._control is not None:
                self._events.attempt = self._control.attempt
                self._events.guard = self._control.ensure_owned
            self._started = perf_counter()
            run.status = RunStatus.RUNNING
            run.started_at = run.started_at or datetime.now(UTC)
            self._events.append(
                db,
                RunEventType.RUN_STARTED,
                RunEventStatus.STARTED,
                input_payload={"input_text": run.input_text, "agent_id": str(run.agent_id)},
            )
            db.commit()
            if agent.status != AgentStatus.ACTIVE:
                raise AgentExecutionError("The agent is not active.", code="agent_not_active")
            self._thread_id, self._user_id = run.thread_id, run.created_by_user_id
            return RunJob(
                run_id=run.id,
                organization_id=run.organization_id,
                agent_id=run.agent_id,
                user_id=run.created_by_user_id,
                input_text=run.input_text,
                instructions=agent.instructions,
                thread_id=run.thread_id,
                workspace_memory_enabled=agent.workspace_memory_enabled,
                knowledge_source_ids=granted_sources(db, run.organization_id, [agent.id]).get(
                    agent.id, ()
                ),
            )

    def memory_used(self, usage: dict[str, Any]) -> None:
        """Count-only record of the memory injected into this run (no memory text)."""
        with self._sessions() as db:
            run = db.get(AgentRun, self._run_id, with_for_update=True)
            run.memory_context = usage
            db.commit()

    def node_started(self, node: str, payload: dict[str, Any]) -> None:
        self._events.write(
            RunEventType.NODE_STARTED, RunEventStatus.STARTED, node=node, input_payload=payload
        )
        if self._tracer is not None:
            # Opened after the event write, so the span times the node's work.
            self._node_spans[node] = self._tracer.open(
                SpanType.GRAPH_NODE, NODE_LABELS.get(node, node), input_summary=keys(payload)
            )

    def node_completed(self, node: str, payload: dict[str, Any], duration_ms: int) -> None:
        if self._tracer is not None:
            self._tracer.close(
                self._node_spans.pop(node, None),
                output_summary=keys(payload),
                metadata=node_metadata(payload),
            )
        self._steps += 1
        self._events.write(
            RunEventType.NODE_COMPLETED,
            RunEventStatus.COMPLETED,
            node=node,
            output_payload=payload,
            duration_ms=duration_ms,
        )

    def node_failed(self, node: str, error: BaseException, duration_ms: int) -> None:
        self.failed_node = node
        code, message, details = safe_error(error)
        if self._tracer is not None:
            self._tracer.close(
                self._node_spans.pop(node, None),
                SpanStatus.FAILED,
                error_code=code,
                error_message=message,
            )
        self._events.write(
            RunEventType.NODE_FAILED,
            RunEventStatus.FAILED,
            node=node,
            output_payload={**details, "error_code": code},
            error_message=message,
            duration_ms=duration_ms,
        )

    def _settle(self, db: Session, outcome: str, code: str | None, message: str | None):
        if self._control is not None:
            return self._control.settle(db, outcome, code, message)
        return None

    def _finish(self, status: RunStatus, state: AgentState | None, error: RunError | None):
        duration = self._duration()
        with self._sessions() as db:
            run = db.get(AgentRun, self._run_id, with_for_update=True)
            self._settle(
                db,
                "failed" if error else "completed",
                error["code"] if error else None,
                error["message"] if error else None,
            )
            run.status = status
            run.completed_at = datetime.now(UTC)
            run.duration_ms = duration
            run.step_count = self._steps
            if state is not None:
                run.state_snapshot = RunStateSnapshot.from_state(state, error).model_dump(
                    mode="json"
                )
            if error:
                run.error_code = error["code"]
                run.error_message = error["message"]
                self._events.append(
                    db,
                    RunEventType.RUN_FAILED,
                    RunEventStatus.FAILED,
                    output_payload={"error_code": error["code"]},
                    error_message=error["message"],
                    duration_ms=duration,
                )
            else:
                run.final_output = to_jsonable_python(state["final_output"])
                if self._memory_settings is not None and self._thread_id is not None:
                    remember_agent_result(
                        db,
                        self._memory_settings,
                        self._events,
                        organization_id=run.organization_id,
                        thread_id=self._thread_id,
                        run_id=run.id,
                        user_id=self._user_id,
                        state=state,
                    )
                self._events.append(
                    db,
                    RunEventType.RUN_COMPLETED,
                    RunEventStatus.COMPLETED,
                    output_payload=run.final_output,
                    duration_ms=duration,
                )
            db.commit()

    def complete(self, state: AgentState) -> None:
        self._finish(RunStatus.COMPLETED, state, None)

    def fail(
        self,
        code: str,
        message: str,
        state: AgentState | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        error: RunError = {"code": code, "message": message, "node": self.failed_node}
        if details:
            error["details"] = to_jsonable_python(details)
        self._finish(RunStatus.FAILED, state, error)

    def retry(
        self,
        code: str,
        message: str,
        state: AgentState | None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """End this attempt with a transient failure; the job is re-queued with backoff."""
        error: RunError = {"code": code, "message": message, "node": self.failed_node}
        if details:
            error["details"] = to_jsonable_python(details)
        with self._sessions() as db:
            run = db.get(AgentRun, self._run_id, with_for_update=True)
            next_retry_at = self._settle(db, "retry", code, message)
            run.status = RunStatus.QUEUED
            if state is not None:
                run.state_snapshot = RunStateSnapshot.from_state(state, error).model_dump(
                    mode="json"
                )
            self._events.append(
                db,
                RunEventType.RETRY_SCHEDULED,
                RunEventStatus.FAILED,
                output_payload={
                    "error_code": code,
                    "attempt": self._control.attempt,
                    "max_attempts": self._control.max_attempts,
                    "next_retry_at": next_retry_at,
                },
                error_message=message,
            )
            db.commit()

    def cancel(self, state: AgentState | None) -> None:
        """Record a cooperative cancellation observed between graph stages."""
        with self._sessions() as db:
            run = db.get(AgentRun, self._run_id, with_for_update=True)
            self._settle(db, "cancelled", "cancelled", "The run was cancelled.")
            run.status = RunStatus.CANCELLED
            run.completed_at = datetime.now(UTC)
            run.duration_ms = self._duration()
            run.step_count = self._steps
            if state is not None:
                run.state_snapshot = RunStateSnapshot.from_state(state, None).model_dump(
                    mode="json"
                )
            self._events.append(
                db,
                RunEventType.RUN_CANCELLED,
                RunEventStatus.FAILED,
                error_message="The run was cancelled.",
                duration_ms=run.duration_ms,
            )
            db.commit()
