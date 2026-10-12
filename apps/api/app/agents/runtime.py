import logging
from collections.abc import Callable
from time import perf_counter
from uuid import UUID

from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session, sessionmaker

from app.agents.context import RunContext
from app.agents.errors import AgentRuntimeError
from app.agents.graph import compiled_agent_graph
from app.agents.providers import LLMProvider
from app.agents.recorder import RunJob, RunRecorder
from app.agents.state import AgentState
from app.agents.tools import ToolExecutionContext, ToolProvider, ToolRegistry, ToolResolver
from app.core.config import Settings
from app.jobs.control import JobCancelled, JobControl, JobLost
from app.memory.context import MemoryContext, build_context
from app.models.observability import SpanType
from app.observability.tools import TracedResolver
from app.observability.tracer import Tracer, memory_metadata

logger = logging.getLogger(__name__)
GENERIC_FAILURE = "The agent run failed due to an internal error."
# Builds a provider bound to one organization, so a run can only reach that tenant's tools.
ProviderFactory = Callable[[ToolExecutionContext], ToolProvider]


def initial_state(job: RunJob) -> AgentState:
    return {
        "run_id": str(job.run_id),
        "organization_id": str(job.organization_id),
        "agent_id": str(job.agent_id),
        "user_input": job.input_text,
        "instructions": job.instructions,
        "tool_results": [],
        "errors": [],
    }


class AgentRuntime:
    """Executes persisted runs; called by the background worker (M7) with a JobControl.

    Holds only shared, immutable collaborators; everything run-specific is created inside
    `execute`, so one instance can serve concurrent runs.
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        tools: ToolRegistry,
        llm: LLMProvider,
        graph: CompiledStateGraph | None = None,
        providers: dict[str, ProviderFactory] | None = None,
        memory_settings: Settings | None = None,
    ):
        # M8: when set, runs receive bounded thread/agent/workspace memory and write facts back.
        self._memory_settings = memory_settings
        self._sessions = sessions
        self._tools = tools
        self._providers = providers or {}
        self._llm = llm
        self._graph = graph or compiled_agent_graph()

    def _load_memory(
        self, job: RunJob, recorder: RunRecorder, tracer: Tracer | None = None
    ) -> MemoryContext | None:
        """Retrieval runs in the worker, once per attempt, from PostgreSQL."""
        if self._memory_settings is None:
            return None
        started = perf_counter()
        with self._sessions() as db:
            memory = build_context(
                db,
                self._memory_settings,
                organization_id=job.organization_id,
                thread_id=job.thread_id,
                agent_ids=[job.agent_id],
                include_workspace=job.workspace_memory_enabled,
            )
        if job.thread_id is not None or not memory.empty:
            recorder.memory_used(memory.usage())
            if tracer is not None:
                tracer.add(
                    SpanType.MEMORY_RETRIEVAL,
                    "Memory retrieval",
                    duration_ms=round((perf_counter() - started) * 1000),
                    metadata=memory_metadata(memory.usage()),
                )
        return memory

    def execute(
        self, run_id: UUID, control: JobControl | None = None, tracer: Tracer | None = None
    ) -> None:
        recorder = RunRecorder(self._sessions, run_id, control, self._memory_settings, tracer)
        try:
            job = recorder.start()
        except AgentRuntimeError as error:
            if not recorder.claimed:
                raise
            recorder.fail(error.code, error.message, None)
            return
        execution = ToolExecutionContext(
            organization_id=job.organization_id,
            user_id=job.user_id,
            run_id=job.run_id,
            knowledge_source_ids=job.knowledge_source_ids,
        )
        resolver = ToolResolver(
            self._tools,
            {source: factory(execution) for source, factory in self._providers.items()},
        )
        if tracer is not None:
            resolver = TracedResolver(resolver, tracer)
        memory = self._load_memory(job, recorder, tracer)
        context = RunContext(
            execution=execution,
            tools=resolver,
            llm=self._llm,
            recorder=recorder,
            memory=memory,
        )
        state = initial_state(job)
        try:
            for values in self._graph.stream(state, context=context, stream_mode="values"):
                state = values
                if control is not None:
                    control.checkpoint()
        except JobCancelled:
            recorder.cancel(state)
            return
        except JobLost:
            logger.warning("Agent run %s: attempt no longer owns its job; stopping", run_id)
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
        except Exception as error:
            logger.exception("Agent run %s failed (%s)", run_id, type(error).__name__)
            recorder.fail("agent_execution_failed", GENERIC_FAILURE, state)
            return
        if "final_output" not in state:
            recorder.fail("agent_execution_failed", "The agent produced no response.", state)
            return
        recorder.complete(state)
