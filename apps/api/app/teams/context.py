from dataclasses import dataclass, replace
from typing import Any, Protocol

from app.agents.tools import ToolExecutionContext, ToolResolver
from app.memory.context import MemoryContext
from app.policies.engine import PolicyDecision
from app.teams.config import MemberConfig, TeamConfig
from app.teams.provider import TeamProvider
from app.teams.toolbox import AgentToolbox

MAX_REVISIONS = 1


@dataclass(frozen=True)
class TeamLimits:
    """Loop bounds. The supervisor may request at most `max_revisions` rewrites; the
    iteration cap bounds supervisor reviews, and LangGraph's recursion limit is a backstop."""

    max_revisions: int = MAX_REVISIONS
    max_iterations: int | None = None  # None: derived from the plan length
    recursion_limit: int = 64

    def iterations_for(self, plan_length: int) -> int:
        if self.max_iterations is not None:
            return self.max_iterations
        # One review after planning and one after each agent, including revision rounds.
        return plan_length + 2 * self.max_revisions + 1


class TeamRecorder(Protocol):
    def plan_created(self, supervisor: MemberConfig, plan: dict[str, Any], duration_ms: int): ...

    def handoff(self, member: MemberConfig, task: str, payload: dict[str, Any]) -> None: ...

    def agent_completed(
        self, member: MemberConfig, output: dict, tool_calls: list, duration_ms: int
    ) -> None: ...

    def agent_failed(
        self, member: MemberConfig, error: BaseException, duration_ms: int, fatal: bool
    ) -> None: ...

    def validation_failed(self, member: MemberConfig, result: dict[str, Any]) -> None: ...

    def revision_requested(self, supervisor: MemberConfig, revision: int, issues: list) -> None: ...

    def action_proposed(self, supervisor: MemberConfig, proposal: dict[str, Any]) -> None: ...

    def policy_decided(
        self, supervisor: MemberConfig, proposal: dict[str, Any], policy: PolicyDecision
    ) -> None:
        """Record policy_allowed or policy_denied."""

    def request_approval(
        self, supervisor: MemberConfig, proposal: dict[str, Any], policy: PolicyDecision
    ) -> str:
        """Persist an approval request; return its id."""

    def execute_action(self, proposal: dict[str, Any]) -> dict[str, Any]:
        """Run the allowed action once and persist the execution."""


@dataclass(frozen=True)
class TeamRunContext:
    """Per-run dependencies passed to LangGraph as `context`; never part of state."""

    execution: ToolExecutionContext
    team: TeamConfig
    tools: ToolResolver
    provider: TeamProvider
    recorder: TeamRecorder
    limits: TeamLimits = TeamLimits()
    # M8: memory for the supervisor (thread + supervisor agent + opted-in workspace). Only the
    # writer receives a bounded slice of it; other specialists receive none.
    memory: MemoryContext | None = None

    def toolbox(self, member: MemberConfig) -> AgentToolbox:
        # Each member searches only its own agent's knowledge grants.
        execution = replace(self.execution, knowledge_source_ids=member.knowledge_source_ids)
        return AgentToolbox(self.tools, member.tool_keys, execution)
