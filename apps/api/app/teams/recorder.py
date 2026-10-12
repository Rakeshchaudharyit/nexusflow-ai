from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import UUID

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.actions.service import create_approval, perform_action
from app.agents.errors import AgentExecutionError
from app.agents.events import EventStream
from app.agents.recorder import safe_error
from app.core.config import Settings
from app.jobs.control import JobControl
from app.knowledge.access import granted_sources
from app.memory.writer import remember_team_result
from app.models.agents import Agent, AgentStatus, RunEventStatus, RunEventType, RunStatus
from app.models.approvals import ActionExecution, ApprovalRequest, ApprovalStatus
from app.models.observability import SpanStatus, SpanType
from app.models.teams import AgentTeam, AgentTeamMember, AgentTeamRun, AgentTool, TeamStatus
from app.observability.tracer import Tracer, agent_metadata, keys
from app.policies.engine import Decision, PolicyDecision
from app.teams.config import MemberConfig, TeamConfig, team_problems
from app.teams.errors import TeamExecutionError
from app.teams.state import TeamState, TeamStateSnapshot


def action_summary(state: TeamState) -> dict[str, Any] | None:
    """The action outcome shown with the run result."""
    proposal = state.get("proposed_action")
    if not proposal:
        return None
    policy = state.get("policy_decision") or {}
    result = state.get("action_result") or {}
    status = {
        "allow": "completed" if result.get("status") == "completed" else "failed",
        "require_approval": "awaiting_approval",
        "deny": "denied",
    }.get(policy.get("decision"), "proposed")
    return {
        "action_type": proposal["action_type"],
        "payload": proposal["payload"],
        "decision": policy.get("decision"),
        "rule_key": policy.get("rule_key"),
        "reason": policy.get("reason"),
        "risk_level": policy.get("risk_level"),
        "status": status,
        "approval_id": state.get("approval_request_id"),
        "execution_id": result.get("execution_id"),
        "message": result.get("message"),
        "simulated": True,
    }


def with_action(state: TeamState) -> dict[str, Any] | None:
    output = state.get("final_output")
    action = action_summary(state)
    if output is None and action is None:
        return None
    return to_jsonable_python({**(output or {}), **({"action": action} if action else {})})


@dataclass(frozen=True)
class TeamJob:
    run_id: UUID
    organization_id: UUID
    user_id: UUID
    objective: str
    team: TeamConfig
    thread_id: UUID | None = None
    workspace_memory_enabled: bool = False


ROLE_LABELS = {
    "supervisor": "Supervisor",
    "customer_specialist": "Customer Specialist",
    "researcher": "Researcher",
    "analyst": "Analyst",
    "writer": "Writer",
    "validator": "Validator",
}


class TeamRunRecorder:
    """Persists one team run incrementally: one short transaction per event or status change."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        team_run_id: UUID,
        approval_expire_hours: int = 24,
        control: JobControl | None = None,
        memory_settings: Settings | None = None,
        tracer: Tracer | None = None,
    ):
        # M10: observational spans (agents, policy, approval, action); never business state.
        self._tracer = tracer
        self._agent_spans: dict[str, Any] = {}
        self._policy_span = None
        self._approval_expire_hours = approval_expire_hours
        self._control = control
        # M8: when set, a validated team result in a thread is written to memory.
        self._memory_settings = memory_settings
        self._thread_id: UUID | None = None
        self._user_id: UUID | None = None
        self._team_id: UUID | None = None
        self._sessions = sessions
        self._run_id = team_run_id
        self._events = EventStream(sessions, team_run_id=team_run_id)
        self._steps = 0
        self._started = perf_counter()

    @property
    def claimed(self) -> bool:
        return self._events.organization_id is not None

    def _duration(self) -> int:
        return round((perf_counter() - self._started) * 1000)

    @staticmethod
    def _load_team(db: Session, run: AgentTeamRun) -> tuple[AgentTeam, TeamConfig, list[str]]:
        organization_id = run.organization_id
        team = db.scalar(
            select(AgentTeam).where(
                AgentTeam.id == run.team_id, AgentTeam.organization_id == organization_id
            )
        )
        rows = db.execute(
            select(AgentTeamMember, Agent)
            .join(
                Agent,
                (Agent.id == AgentTeamMember.agent_id)
                & (Agent.organization_id == AgentTeamMember.organization_id),
            )
            .where(
                AgentTeamMember.team_id == team.id,
                AgentTeamMember.organization_id == organization_id,
            )
            .order_by(AgentTeamMember.position, AgentTeamMember.role)
        ).all()
        assignments: dict[UUID, list[str]] = {}
        for tool in db.scalars(
            select(AgentTool)
            .where(
                AgentTool.organization_id == organization_id,
                AgentTool.agent_id.in_([agent.id for _, agent in rows]),
                AgentTool.is_enabled.is_(True),
            )
            .order_by(AgentTool.created_at, AgentTool.tool_key)
        ):
            assignments.setdefault(tool.agent_id, []).append(tool.tool_key)
        knowledge = granted_sources(db, organization_id, [agent.id for _, agent in rows])
        config = TeamConfig(
            team_id=team.id,
            name=team.name,
            members=tuple(
                MemberConfig(
                    member_id=member.id,
                    agent_id=agent.id,
                    agent_name=agent.name,
                    role=member.role,
                    is_required=member.is_required,
                    instructions=agent.instructions,
                    tool_keys=tuple(assignments.get(agent.id, ())),
                    knowledge_source_ids=knowledge.get(agent.id, ()),
                )
                for member, agent in rows
            ),
        )
        inactive = [agent.name for _, agent in rows if agent.status != AgentStatus.ACTIVE]
        return team, config, inactive

    def start(self) -> TeamJob:
        """Move a queued team run to running and build its server-side configuration."""
        with self._sessions() as db:
            run = db.scalar(
                select(AgentTeamRun).where(AgentTeamRun.id == self._run_id).with_for_update()
            )
            if run is None or run.status != RunStatus.QUEUED:
                raise AgentExecutionError(
                    "The team run is not waiting to execute.", code="run_not_queued"
                )
            team, config, inactive = self._load_team(db, run)
            # Continue numbering after earlier attempts; the run lock serialises writers.
            self._events.resume(db, run.organization_id)
            if self._control is not None:
                self._events.attempt = self._control.attempt
                self._events.guard = self._control.ensure_owned
            self._user_id = run.created_by_user_id
            self._team_id = run.team_id
            self._thread_id = run.thread_id
            self._started = perf_counter()
            run.status = RunStatus.RUNNING
            run.started_at = run.started_at or datetime.now(UTC)
            self._events.append(
                db,
                RunEventType.TEAM_RUN_STARTED,
                RunEventStatus.STARTED,
                input_payload={
                    "objective": run.objective,
                    "team_name": team.name,
                    "members": [member.describe() for member in config.members],
                },
            )
            db.commit()
            problems = team_problems([member.role for member in config.members], inactive)
            if team.status != TeamStatus.ACTIVE:
                problems.insert(0, "the team is not active")
            if problems:
                raise TeamExecutionError(
                    "The team cannot run: " + "; ".join(problems) + ".", code="team_not_runnable"
                )
            return TeamJob(
                run_id=run.id,
                organization_id=run.organization_id,
                user_id=run.created_by_user_id,
                objective=run.objective,
                team=config,
                thread_id=run.thread_id,
                workspace_memory_enabled=team.workspace_memory_enabled,
            )

    def memory_used(self, usage: dict[str, Any]) -> None:
        """Count-only record of the memory injected into this run (no memory text)."""
        with self._sessions() as db:
            run = db.get(AgentTeamRun, self._run_id, with_for_update=True)
            run.memory_context = usage
            db.commit()

    def _remember(self, db: Session, run: AgentTeamRun, state: TeamState | None) -> None:
        if self._memory_settings is None or self._thread_id is None or state is None:
            return
        remember_team_result(
            db,
            self._memory_settings,
            self._events,
            organization_id=run.organization_id,
            thread_id=self._thread_id,
            team_id=run.team_id,
            run_id=run.id,
            user_id=run.created_by_user_id,
            state=state,
        )

    def _member_event(self, event_type, status, member: MemberConfig, **fields) -> None:
        self._events.write(
            event_type,
            status,
            node=member.role.value,
            agent_id=member.agent_id,
            agent_role=member.role.value,
            **fields,
        )

    def plan_created(self, supervisor: MemberConfig, plan: dict[str, Any], duration_ms: int):
        if self._tracer is not None:
            self._tracer.add(
                SpanType.AGENT,
                f"Supervisor · plan · {supervisor.agent_name}",
                duration_ms=duration_ms,
                agent_id=supervisor.agent_id,
                metadata={
                    "role": "supervisor",
                    "planned_steps": len(plan.get("steps", [])),
                    "roles": [step.get("role") for step in plan.get("steps", [])],
                },
            )
        self._member_event(
            RunEventType.SUPERVISOR_PLAN_CREATED,
            RunEventStatus.COMPLETED,
            supervisor,
            output_payload=plan,
            duration_ms=duration_ms,
        )

    def handoff(self, member: MemberConfig, task: str, payload: dict[str, Any]) -> None:
        self._member_event(
            RunEventType.HANDOFF_STARTED,
            RunEventStatus.STARTED,
            member,
            input_payload={
                "from": "supervisor",
                "to": member.role.value,
                "agent_name": member.agent_name,
                "task": task,
                "context": payload,
            },
        )
        if self._tracer is not None:
            # Opened after the handoff event write, so the span times the agent's work.
            self._agent_spans[member.role.value] = self._tracer.open(
                SpanType.AGENT,
                f"{ROLE_LABELS.get(member.role.value, member.role.value)} · {member.agent_name}",
                agent_id=member.agent_id,
                input_summary=keys(payload),
            )

    def agent_completed(
        self, member: MemberConfig, output: dict, tool_calls: list, duration_ms: int
    ) -> None:
        self._steps += 1
        if self._tracer is not None:
            self._tracer.close(
                self._agent_spans.pop(member.role.value, None),
                output_summary=keys(output),
                metadata=agent_metadata(member.role.value, output, tool_calls),
            )
        self._member_event(
            RunEventType.AGENT_COMPLETED,
            RunEventStatus.COMPLETED,
            member,
            output_payload={"output": output, "tool_calls": tool_calls},
            duration_ms=duration_ms,
        )

    def agent_failed(
        self, member: MemberConfig, error: BaseException, duration_ms: int, fatal: bool
    ) -> None:
        code, message, details = safe_error(error)
        if self._tracer is not None:
            span = self._agent_spans.pop(member.role.value, None)
            if span is None:  # the supervisor failed outside a handoff (plan/review)
                span = self._tracer.open(
                    SpanType.AGENT, f"Supervisor · {member.agent_name}", agent_id=member.agent_id
                )
            self._tracer.close(
                span,
                SpanStatus.FAILED,
                error_code=code,
                error_message=message,
                metadata={"role": member.role.value, "fatal": fatal},
                duration_ms=duration_ms,
            )
        self._member_event(
            RunEventType.AGENT_FAILED,
            RunEventStatus.FAILED,
            member,
            output_payload={**details, "error_code": code, "fatal": fatal},
            error_message=message,
            duration_ms=duration_ms,
        )

    def validation_failed(self, member: MemberConfig, result: dict[str, Any]) -> None:
        self._member_event(
            RunEventType.VALIDATION_FAILED,
            RunEventStatus.FAILED,
            member,
            output_payload=result,
            error_message="The validator rejected the draft.",
        )

    def revision_requested(self, supervisor: MemberConfig, revision: int, issues: list) -> None:
        if self._tracer is not None:
            self._tracer.add(
                SpanType.GRAPH_NODE,
                f"Revision {revision} requested",
                metadata={"revision": revision, "issues": len(issues)},
            )
        self._member_event(
            RunEventType.REVISION_REQUESTED,
            RunEventStatus.STARTED,
            supervisor,
            input_payload={"revision": revision, "issues": issues},
        )

    def action_proposed(self, supervisor: MemberConfig, proposal: dict[str, Any]) -> None:
        if self._tracer is not None:
            # Closed when policy decides (allow/deny) or the approval is requested.
            self._policy_span = self._tracer.open(
                SpanType.POLICY, f"Policy · {proposal['action_type']}", agent_id=supervisor.agent_id
            )
        self._member_event(
            RunEventType.ACTION_PROPOSED,
            RunEventStatus.COMPLETED,
            supervisor,
            output_payload=proposal,
        )

    def policy_decided(
        self, supervisor: MemberConfig, proposal: dict[str, Any], policy: PolicyDecision
    ) -> None:
        allowed = policy.decision == Decision.ALLOW
        self._close_policy(proposal, policy)
        self._member_event(
            RunEventType.POLICY_ALLOWED if allowed else RunEventType.POLICY_DENIED,
            RunEventStatus.COMPLETED if allowed else RunEventStatus.FAILED,
            supervisor,
            output_payload={"action_type": proposal["action_type"], **policy.as_dict()},
            error_message=None if allowed else policy.reason,
        )

    def _close_policy(self, proposal: dict[str, Any], policy: PolicyDecision) -> None:
        if self._tracer is None:
            return
        span = self._policy_span or self._tracer.open(
            SpanType.POLICY, f"Policy · {proposal['action_type']}"
        )
        self._policy_span = None
        self._tracer.close(
            span,
            SpanStatus.FAILED if policy.decision == Decision.DENY else SpanStatus.COMPLETED,
            error_code="policy_denied" if policy.decision == Decision.DENY else None,
            error_message=policy.reason if policy.decision == Decision.DENY else None,
            metadata={
                "action_type": proposal["action_type"],
                "decision": policy.decision.value,
                "risk_level": policy.risk_level.value,
                "rule_key": policy.rule_key,
            },
        )

    def request_approval(
        self, supervisor: MemberConfig, proposal: dict[str, Any], policy: PolicyDecision
    ) -> str:
        self._close_policy(proposal, policy)
        if self._tracer is not None:
            self._tracer.add(
                SpanType.APPROVAL,
                "Approval requested",
                status=SpanStatus.PENDING,
                metadata={
                    "action_type": proposal["action_type"],
                    "risk_level": policy.risk_level.value,
                },
            )
        if self._control is not None:
            self._control.ensure_owned()
        with self._sessions() as db:
            # A restarted attempt reuses the request an earlier attempt already persisted.
            existing = db.scalar(
                select(ApprovalRequest.id).where(
                    ApprovalRequest.team_run_id == self._run_id,
                    ApprovalRequest.organization_id == self._events.organization_id,
                )
            )
            if existing is not None:
                return str(existing)
            approval = create_approval(
                db,
                self._events,
                organization_id=self._events.organization_id,
                team_run_id=self._run_id,
                team_id=self._team_id,
                agent_id=supervisor.agent_id,
                user_id=self._user_id,
                proposal=proposal,
                policy=policy,
                expire_hours=self._approval_expire_hours,
            )
            db.commit()
            return str(approval.id)

    def execute_action(self, proposal: dict[str, Any]) -> dict[str, Any]:
        span = (
            self._tracer.open(SpanType.ACTION, f"Action · {proposal['action_type']}")
            if self._tracer is not None
            else None
        )
        outcome = self._execute_action(proposal)
        if self._tracer is not None:
            failed = outcome.get("status") == "failed"
            self._tracer.close(
                span,
                SpanStatus.FAILED if failed else SpanStatus.COMPLETED,
                error_code="action_failed" if failed else None,
                metadata={
                    "action_type": proposal["action_type"],
                    "status": outcome.get("status"),
                    "simulated": True,
                },
            )
        return outcome

    def _execute_action(self, proposal: dict[str, Any]) -> dict[str, Any]:
        if self._control is not None:
            self._control.ensure_owned()
        with self._sessions() as db:
            # Exactly once across attempts: an earlier attempt's execution is the outcome.
            existing = db.scalar(
                select(ActionExecution).where(
                    ActionExecution.team_run_id == self._run_id,
                    ActionExecution.organization_id == self._events.organization_id,
                )
            )
            if existing is not None:
                return {
                    "execution_id": str(existing.id),
                    "status": existing.status.value,
                    **existing.result,
                }
            outcome = perform_action(
                db,
                self._events,
                organization_id=self._events.organization_id,
                team_run_id=self._run_id,
                proposal=proposal,
                user_id=self._user_id,
                approval_id=None,
            )
            db.commit()
            return outcome

    def await_approval(self, state: TeamState) -> None:
        """End this request with the run paused; the approval continuation finishes it."""
        with self._sessions() as db:
            run = db.get(AgentTeamRun, self._run_id, with_for_update=True)
            self._settle(db, "awaiting_approval")
            # The analysis is validated even though the action waits: remember the result.
            self._remember(db, run, state)
            run.status = RunStatus.AWAITING_APPROVAL
            run.duration_ms = self._duration()
            run.step_count = self._steps
            run.state_snapshot = TeamStateSnapshot.from_state(state).model_dump(mode="json")
            run.final_output = with_action(state)
            db.commit()

    def _settle(
        self, db: Session, outcome: str, code: str | None = None, message: str | None = None
    ):
        if self._control is not None:
            return self._control.settle(db, outcome, code, message)
        return None

    def _finish(self, status: RunStatus, state: TeamState | None, error: dict | None) -> None:
        duration = self._duration()
        with self._sessions() as db:
            run = db.get(AgentTeamRun, self._run_id, with_for_update=True)
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
                run.state_snapshot = TeamStateSnapshot.from_state(state, error).model_dump(
                    mode="json"
                )
            if error:
                run.error_code = error["code"]
                run.error_message = error["message"]
                # Keep any partial result and the action outcome (e.g. a policy denial).
                run.final_output = with_action(state) if state is not None else None
                self._events.append(
                    db,
                    RunEventType.TEAM_RUN_FAILED,
                    RunEventStatus.FAILED,
                    output_payload={"error_code": error["code"]},
                    error_message=error["message"],
                    duration_ms=duration,
                )
            else:
                run.final_output = with_action(state)
                self._remember(db, run, state)
                self._events.append(
                    db,
                    RunEventType.TEAM_RUN_COMPLETED,
                    RunEventStatus.COMPLETED,
                    output_payload=run.final_output,
                    duration_ms=duration,
                )
            db.commit()

    def complete(self, state: TeamState) -> None:
        self._finish(RunStatus.COMPLETED, state, None)

    def fail(
        self, code: str, message: str, state: TeamState | None, details: dict | None = None
    ) -> None:
        error = {"code": code, "message": message}
        if details:
            error["details"] = to_jsonable_python(details)
        self._finish(RunStatus.FAILED, state, error)

    def retry(
        self, code: str, message: str, state: TeamState | None, details: dict | None = None
    ) -> None:
        """End this attempt with a transient failure; the job is re-queued with backoff."""
        error = {"code": code, "message": message}
        if details:
            error["details"] = to_jsonable_python(details)
        with self._sessions() as db:
            run = db.get(AgentTeamRun, self._run_id, with_for_update=True)
            next_retry_at = self._settle(db, "retry", code, message)
            run.status = RunStatus.QUEUED
            if state is not None:
                run.state_snapshot = TeamStateSnapshot.from_state(state, error).model_dump(
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

    def cancel(self, state: TeamState | None) -> None:
        """Record a cooperative cancellation observed between graph stages."""
        with self._sessions() as db:
            # Approval before run: the same lock order as the review endpoint.
            approval = db.scalar(
                select(ApprovalRequest)
                .where(
                    ApprovalRequest.team_run_id == self._run_id,
                    ApprovalRequest.organization_id == self._events.organization_id,
                )
                .with_for_update()
            )
            run = db.get(AgentTeamRun, self._run_id, with_for_update=True)
            self._settle(db, "cancelled", "cancelled", "The team run was cancelled.")
            if approval is not None and approval.status == ApprovalStatus.PENDING:
                approval.status = ApprovalStatus.CANCELLED
            run.status = RunStatus.CANCELLED
            run.completed_at = datetime.now(UTC)
            run.duration_ms = self._duration()
            run.step_count = self._steps
            if state is not None:
                run.state_snapshot = TeamStateSnapshot.from_state(state).model_dump(mode="json")
                run.final_output = with_action(state)
            self._events.append(
                db,
                RunEventType.TEAM_RUN_CANCELLED,
                RunEventStatus.FAILED,
                error_message="The team run was cancelled.",
                duration_ms=run.duration_ms,
            )
            db.commit()
