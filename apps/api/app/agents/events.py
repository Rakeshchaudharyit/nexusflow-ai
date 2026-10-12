from collections.abc import Callable
from threading import Lock
from typing import Any
from uuid import UUID

from pydantic_core import to_jsonable_python
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.agents import AgentRunEvent, RunEventStatus, RunEventType


class EventStream:
    """Numbers and stores the immutable events of one run (agent run or team run).

    The counter lives on this per-run instance, so sequences are 1..n in recording order;
    the (run, sequence) unique constraints reject duplicates.
    """

    def __init__(
        self,
        sessions: sessionmaker[Session] | None,
        *,
        run_id: UUID | None = None,
        team_run_id: UUID | None = None,
    ):
        if (run_id is None) == (team_run_id is None):
            raise ValueError("An event stream belongs to exactly one run")
        self._sessions = sessions
        self._run_id = run_id
        self._team_run_id = team_run_id
        self.organization_id: UUID | None = None
        # Set by background jobs (M7): the attempt is stored on every event, and the guard
        # stops a worker that lost ownership of its job from writing further events.
        self.attempt: int | None = None
        self.guard: Callable[[], None] | None = None
        self._sequence = 0
        self._lock = Lock()

    def resume(self, db: Session, organization_id: UUID) -> "EventStream":
        """Continue numbering after the run's last event (e.g. after a human approval).

        Call only while holding the run's row lock, so no other writer can append concurrently.
        """
        parent = (
            AgentRunEvent.run_id == self._run_id
            if self._run_id is not None
            else AgentRunEvent.team_run_id == self._team_run_id
        )
        self.organization_id = organization_id
        self._sequence = db.scalar(
            select(func.coalesce(func.max(AgentRunEvent.sequence), 0)).where(
                parent, AgentRunEvent.organization_id == organization_id
            )
        )
        return self

    def append(
        self,
        db: Session,
        event_type: RunEventType,
        status: RunEventStatus,
        *,
        node: str | None = None,
        agent_id: UUID | None = None,
        agent_role: str | None = None,
        input_payload: dict[str, Any] | None = None,
        output_payload: dict[str, Any] | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Add an event to an open session; the caller's transaction commits it."""
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
        db.add(
            AgentRunEvent(
                organization_id=self.organization_id,
                run_id=self._run_id,
                team_run_id=self._team_run_id,
                sequence=sequence,
                event_type=event_type,
                node_name=node,
                agent_id=agent_id,
                agent_role=agent_role,
                status=status,
                input_payload=to_jsonable_python(input_payload),
                output_payload=to_jsonable_python(output_payload),
                error_message=error_message,
                duration_ms=duration_ms,
                attempt=self.attempt,
            )
        )

    def write(self, event_type: RunEventType, status: RunEventStatus, **fields) -> None:
        """Record one event in its own short transaction."""
        if self.guard is not None:
            self.guard()
        with self._sessions() as db:
            self.append(db, event_type, status, **fields)
            db.commit()
