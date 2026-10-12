import logging
from time import perf_counter
from uuid import UUID

from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session, sessionmaker

from app.actions.service import FAILURE
from app.agents.errors import AgentRuntimeError
from app.agents.runtime import ProviderFactory
from app.agents.tools import ToolExecutionContext, ToolRegistry, ToolResolver
from app.core.config import Settings
from app.jobs.control import JobCancelled, JobControl, JobLost
from app.memory.context import MemoryContext, build_context
from app.models.observability import SpanType
from app.observability.tools import TracedResolver
from app.observability.tracer import Tracer, memory_metadata
from app.teams.context import TeamLimits, TeamRunContext
from app.teams.graph import compiled_team_graph
from app.teams.provider import TeamProvider
from app.teams.recorder import TeamJob, TeamRunRecorder
from app.teams.state import TeamState

logger = logging.getLogger(__name__)
GENERIC_FAILURE = "The team run failed due to an internal error."


def initial_state(job: TeamJob) -> TeamState:
    return {
        "run_id": str(job.run_id),
        "organization_id": str(job.organization_id),
        "team_id": str(job.team.team_id),
        "objective": job.objective,
        "iteration": 0,
        "revisions": 0,
        "errors": [],
    }


class TeamRuntime:
    """Executes persisted team runs; called by the background worker (M7) with a JobControl.

    Tools resolve through the same ToolResolver and provider factories as single-agent runs,
    so MCP calls go through the M4 adapter bound to the run's organization.
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        tools: ToolRegistry,
        provider: TeamProvider,
        providers: dict[str, ProviderFactory] | None = None,
        limits: TeamLimits | None = None,
        graph: CompiledStateGraph | None = None,
        approval_expire_hours: int = 24,
        memory_settings: Settings | None = None,
    ):
        self._memory_settings = memory_settings
        self._approval_expire_hours = approval_expire_hours
        self._sessions = sessions
        self._tools = tools
        self._provider = provider
        self._providers = providers or {}
        self._limits = limits or TeamLimits()
        self._graph = graph or compiled_team_graph()

    def _load_memory(
        self, job: TeamJob, recorder: TeamRunRecorder, tracer: Tracer | None = None
    ) -> MemoryContext | None:
        if self._memory_settings is None:
            return None
        started = perf_counter()
        with self._sessions() as db:
            memory = build_context(
                db,
                self._memory_settings,
                organization_id=job.organization_id,
                thread_id=job.thread_id,
                agent_ids=[job.team.supervisor.agent_id],
                include_workspace=job.workspace_memory_enabled,
            )
        if job.thread_id is not None or not memory.empty:
            recorder.memory_used(memory.usage())
            if tracer is not None:
                tracer.add(
                    SpanType.MEMORY_RETRIEVAL,
                    "Memory retrieval · supervisor",
                    duration_ms=round((perf_counter() - started) * 1000),
                    metadata=memory_metadata(memory.usage()),
                )
        return memory

    def execute(
        self, team_run_id: UUID, control: JobControl | None = None, tracer: Tracer | None = None
    ) -> None:
        recorder = TeamRunRecorder(
            self._sessions,
            team_run_id,
            self._approval_expire_hours,
            control,
            self._memory_settings,
            tracer,
        )
        try:
            job = recorder.start()
        except AgentRuntimeError as error:
            if not recorder.claimed:
                raise
            recorder.fail(error.code, error.message, None)
            return
        execution = ToolExecutionContext(
            organization_id=job.organization_id, user_id=job.user_id, run_id=job.run_id
        )
        resolver = ToolResolver(
            self._tools,
            {source: factory(execution) for source, factory in self._providers.items()},
        )
        context = TeamRunContext(
            execution=execution,
            team=job.team,
            tools=TracedResolver(resolver, tracer) if tracer is not None else resolver,
            provider=self._provider,
            recorder=recorder,
            limits=self._limits,
            memory=self._load_memory(job, recorder, tracer),
        )
        state = initial_state(job)
        try:
            for values in self._graph.stream(
                state,
                context=context,
                stream_mode="values",
                config={"recursion_limit": self._limits.recursion_limit},
            ):
                state = values
                if control is not None:
                    control.checkpoint()
        except JobCancelled:
            # Once a business action has executed, the run's outcome is that action; a late
            # cancellation must not relabel it, so finish normally instead.
            if not state.get("action_result"):
                recorder.cancel(state)
                return
        except JobLost:
            logger.warning("Team run %s: attempt no longer owns its job; stopping", team_run_id)
            return
        except AgentRuntimeError as error:
            if control is not None and control.cancel_requested():
                # A pending cancellation wins over a retry; the run must not linger queued.
                recorder.cancel(state)
            elif control is not None and control.should_retry(error.code):
                recorder.retry(error.code, error.message, state, error.details)
            else:
                recorder.fail(error.code, error.message, state, error.details)
            return
        except GraphRecursionError:
            recorder.fail(
                "iteration_limit_exceeded", "The team reached its iteration limit.", state
            )
            return
        except Exception as error:
            logger.exception("Team run %s failed (%s)", team_run_id, type(error).__name__)
            recorder.fail("team_execution_failed", GENERIC_FAILURE, state)
            return
        if tracer is not None and "proposed_action" in state and not state["proposed_action"]:
            tracer.add(
                SpanType.POLICY,
                "No action proposed",
                metadata={"decision": "none", "reason": "the objective asks for no action"},
            )
        policy = state.get("policy_decision") or {}
        if policy.get("decision") == "require_approval" and state.get("approval_request_id"):
            recorder.await_approval(state)
        elif (state.get("action_result") or {}).get("status") == "failed":
            recorder.fail("action_failed", FAILURE, state)
        elif "final_output" in state:
            recorder.complete(state)
        elif policy.get("decision") == "deny":
            recorder.fail("policy_denied", policy["reason"], state)
        else:
            recorder.fail("team_execution_failed", "The team produced no result.", state)
