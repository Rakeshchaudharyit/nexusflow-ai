from typing import Any, NotRequired, TypedDict

from pydantic import BaseModel

FINALIZE = "finalize"


class PlanStep(TypedDict):
    step: int
    role: str
    agent_id: str
    agent_name: str
    task: str


class TeamState(TypedDict):
    """Shared multi-agent state. Every value is JSON-serializable.

    Specialists never receive this whole object; each gets a role-specific slice (see
    `app.teams.graph.CONTEXT_FOR`). Clients, sessions and secrets live in the runtime context.
    """

    run_id: str
    organization_id: str
    team_id: str
    objective: str
    iteration: int
    revisions: int
    company: NotRequired[str]
    plan: NotRequired[list[PlanStep]]
    current_agent: NotRequired[str]
    next_agent: NotRequired[str]
    completed_agents: NotRequired[list[str]]
    failed_agents: NotRequired[list[str]]
    customer_context: NotRequired[dict[str, Any]]
    research_context: NotRequired[dict[str, Any]]
    analysis_context: NotRequired[dict[str, Any]]
    draft_output: NotRequired[dict[str, Any]]
    validation_result: NotRequired[dict[str, Any]]
    final_output: NotRequired[dict[str, Any]]
    errors: NotRequired[list[dict[str, Any]]]
    # M6: one business action proposed after validation, and what policy did with it.
    proposed_action: NotRequired[dict[str, Any] | None]
    policy_decision: NotRequired[dict[str, str]]
    approval_request_id: NotRequired[str]
    action_result: NotRequired[dict[str, Any]]


class TeamStateSnapshot(BaseModel):
    """Allow-listed state persisted on agent_team_runs.state_snapshot."""

    run_id: str
    organization_id: str
    team_id: str
    objective: str
    iteration: int = 0
    revisions: int = 0
    company: str | None = None
    plan: list[dict[str, Any]] = []
    current_agent: str | None = None
    completed_agents: list[str] = []
    failed_agents: list[str] = []
    customer_context: dict[str, Any] | None = None
    research_context: dict[str, Any] | None = None
    analysis_context: dict[str, Any] | None = None
    draft_output: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    final_output: dict[str, Any] | None = None
    errors: list[dict[str, Any]] = []
    proposed_action: dict[str, Any] | None = None
    policy_decision: dict[str, str] | None = None
    approval_request_id: str | None = None
    action_result: dict[str, Any] | None = None

    @classmethod
    def from_state(cls, state: TeamState, error: dict[str, Any] | None = None):
        fields = {key: state[key] for key in cls.model_fields if key in state}
        fields["errors"] = [*state.get("errors", []), *([error] if error else [])]
        return cls(**fields)
