"""Supervisor-led multi-agent graph.

    START → supervisor_plan → supervisor_review ─┬→ customer_specialist ─┐
                                ▲                ├→ researcher ──────────┤
                                │                ├→ analyst ─────────────┤
                                │                ├→ writer ──────────────┤
                                │                ├→ validator ───────────┤
                                └────────────────┴────────────────────────┘
                                                 └→ finalize → END

Every agent hands its result back to the supervisor, which chooses the next node through a
conditional edge. The choice comes from the provider but must be legal for the current state
(plan order, draft before validation, validation before finalize). Rewrites are capped by
`TeamLimits.max_revisions` and supervisor reviews by an iteration limit.
"""

from collections.abc import Callable
from functools import cache
from time import perf_counter
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from app.actions.schemas import validate_payload
from app.models.teams import SPECIALIST_ROLES, TeamRole
from app.policies.engine import Decision, PolicyDecision, RiskLevel, evaluate
from app.teams.config import ROLE_ORDER
from app.teams.context import TeamRunContext
from app.teams.errors import TeamExecutionError
from app.teams.provider import SupervisorView
from app.teams.specialists import WORK, AgentTask
from app.teams.state import FINALIZE, TeamState

Node = Callable[[TeamState, Runtime[TeamRunContext]], dict]
SPECIALISTS = tuple(role.value for role in SPECIALIST_ROLES)
INFORMATION_ROLES = (TeamRole.CUSTOMER_SPECIALIST.value, TeamRole.RESEARCHER.value)
WRITER, VALIDATOR = TeamRole.WRITER.value, TeamRole.VALIDATOR.value
AGENT_ROLES = tuple(role.value for role in ROLE_ORDER)

# Context minimization: each role receives only the slice of shared state it needs.
CONTEXT_FOR: dict[str, Callable[[TeamState], dict[str, Any]]] = {
    "customer_specialist": lambda s: {"objective": s["objective"], "company": s["company"]},
    "researcher": lambda s: {"objective": s["objective"], "company": s["company"]},
    "analyst": lambda s: {
        "company": s["company"],
        "customer_context": s.get("customer_context"),
        "research_context": s.get("research_context"),
    },
    "writer": lambda s: {
        "objective": s["objective"],
        "company": s["company"],
        "customer_context": s.get("customer_context"),
        "research_context": s.get("research_context"),
        "analysis_context": s.get("analysis_context"),
        "revision_feedback": (s.get("validation_result") or {}).get("issues", []),
    },
    "validator": lambda s: {
        "draft": s["draft_output"],
        "customer_context": s.get("customer_context"),
        "research_context": s.get("research_context"),
        "analysis_context": s.get("analysis_context"),
    },
}
STATE_KEY = {
    "customer_specialist": "customer_context",
    "researcher": "research_context",
    "analyst": "analysis_context",
    "writer": "draft_output",
    "validator": "validation_result",
}


def elapsed_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def legal_next(state: TeamState) -> list[str]:
    """Steps the supervisor may choose next. Always moves the run forward."""
    plan_roles = [step["role"] for step in state["plan"]]
    finished = {*state.get("completed_agents", []), *state.get("failed_agents", [])}
    pending = [role for role in plan_roles if role in SPECIALISTS and role not in finished]
    if pending:
        gathering = [role for role in pending if role in INFORMATION_ROLES]
        return gathering or pending  # the analyst works on gathered findings
    draft = state.get("draft_output")
    validation = state.get("validation_result")
    if draft is None:
        return [WRITER]
    if validation is None or validation.get("revision") != draft.get("revision"):
        return [VALIDATOR]
    return [FINALIZE] if validation["valid"] else [WRITER]


def supervised(node: Node) -> Node:
    """Record supervisor failures as agent_failed events before they end the run."""

    def run(state: TeamState, runtime: Runtime[TeamRunContext]) -> dict:
        started = perf_counter()
        try:
            return node(state, runtime)
        except Exception as error:
            context = runtime.context
            context.recorder.agent_failed(context.team.supervisor, error, elapsed_ms(started), True)
            raise

    return run


def supervisor_plan(state: TeamState, runtime: Runtime[TeamRunContext]) -> dict:
    context = runtime.context
    started = perf_counter()
    try:
        plan = context.provider.plan(state["objective"], context.team.roster)
    except TeamExecutionError as error:
        # An objective with nothing to analyze but an action request still goes through
        # policy, which denies actions without a validated result.
        if error.code == "objective_not_supported" and context.provider.propose_action(
            state["objective"], None
        ):
            return {"plan": [], "current_agent": TeamRole.SUPERVISOR.value}
        raise
    company = plan.get("company")
    if not isinstance(company, str) or not 0 < len(company) <= 120:
        raise TeamExecutionError("The supervisor produced an invalid plan.", code="invalid_plan")
    steps, seen = [], set()
    for item in plan.get("steps", []):
        role = item.get("role")
        member = context.team.member(role) if role in AGENT_ROLES else None
        if member is None or role in seen:
            # Plans may only name roles the server-built team actually has, once each.
            raise TeamExecutionError(
                "The supervisor produced an invalid plan.", code="invalid_plan"
            )
        seen.add(role)
        steps.append(
            {
                "step": len(steps) + 1,
                "role": role,
                "agent_id": str(member.agent_id),
                "agent_name": member.agent_name,
                "task": str(item.get("task", ""))[:300],
            }
        )
    if not seen & set(SPECIALISTS) or not {WRITER, VALIDATOR} <= seen:
        raise TeamExecutionError("The supervisor produced an invalid plan.", code="invalid_plan")
    context.recorder.plan_created(
        context.team.supervisor, {"company": company, "steps": steps}, elapsed_ms(started)
    )
    return {
        "company": company,
        "plan": steps,
        "completed_agents": [],
        "failed_agents": [],
        "current_agent": TeamRole.SUPERVISOR.value,
    }


def supervisor_review(state: TeamState, runtime: Runtime[TeamRunContext]) -> dict:
    context = runtime.context
    iteration = state["iteration"] + 1
    if iteration > context.limits.iterations_for(len(state["plan"])):
        raise TeamExecutionError(
            "The team reached its iteration limit.", code="iteration_limit_exceeded"
        )
    legal = legal_next(state)
    validation = state.get("validation_result")
    view = SupervisorView(
        plan_roles=[step["role"] for step in state["plan"]],
        completed=list(state.get("completed_agents", [])),
        failed=list(state.get("failed_agents", [])),
        legal=legal,
        has_draft="draft_output" in state,
        draft_valid=validation.get("valid") if validation else None,
        revisions=state["revisions"],
    )
    decision = context.provider.decide(view)
    if decision not in legal:
        raise TeamExecutionError(
            "The supervisor chose a step that is not allowed now.",
            code="invalid_supervisor_decision",
            details={"decision": str(decision)[:40]},
        )
    update: dict[str, Any] = {
        "iteration": iteration,
        "next_agent": decision,
        "current_agent": TeamRole.SUPERVISOR.value,
    }
    if decision == WRITER and "draft_output" in state:
        revisions = state["revisions"] + 1
        if revisions > context.limits.max_revisions:
            raise TeamExecutionError(
                "The validator rejected the draft after the allowed revisions.",
                code="revision_limit_exceeded",
                details={"issues": "; ".join(validation["issues"])[:400]},
            )
        context.recorder.revision_requested(
            context.team.supervisor, revisions, validation["issues"]
        )
        update["revisions"] = revisions
    return update


def agent_node(role: str) -> Node:
    work = WORK[role]

    def run(state: TeamState, runtime: Runtime[TeamRunContext]) -> dict:
        context = runtime.context
        member = context.team.member(role)
        step = next(item for item in state["plan"] if item["role"] == role)
        task_input = CONTEXT_FOR[role](state)
        if role == WRITER and context.memory is not None:
            # Only notes about this company, at most three: handoffs stay minimized.
            notes = context.memory.notes_about(state["company"], limit=3)
            if notes:
                task_input["memory_notes"] = notes
        context.recorder.handoff(member, step["task"], task_input)
        started = perf_counter()
        try:
            result = work(
                AgentTask(
                    input=task_input,
                    instructions=member.instructions,
                    toolbox=context.toolbox(member),
                    provider=context.provider,
                )
            )
        except Exception as error:
            # Optional specialists may fail without ending the run; the writer and
            # validator are always required because the result depends on them.
            fatal = member.is_required or role not in SPECIALISTS
            context.recorder.agent_failed(member, error, elapsed_ms(started), fatal)
            if fatal:
                raise
            code = getattr(error, "code", "internal_error")
            return {
                "failed_agents": [*state.get("failed_agents", []), role],
                "errors": [*state.get("errors", []), {"role": role, "code": code}],
                "current_agent": role,
            }
        output = dict(result.output)
        if role == WRITER:
            output["revision"] = state["revisions"]
        if role == VALIDATOR:
            output["revision"] = state["draft_output"]["revision"]
        context.recorder.agent_completed(member, output, result.tool_calls, elapsed_ms(started))
        if role == VALIDATOR and not output["valid"]:
            context.recorder.validation_failed(member, output)
        return {
            STATE_KEY[role]: output,
            "completed_agents": [*state.get("completed_agents", []), role],
            "current_agent": role,
        }

    return run


def finalize(state: TeamState, runtime: Runtime[TeamRunContext]) -> dict:
    analysis = state["analysis_context"]
    draft = state["draft_output"]
    validation = state["validation_result"]
    sources = [
        context["source"]
        for key in ("customer_context", "research_context")
        if (context := state.get(key)) and context.get("source")
    ]
    return {
        "final_output": {
            "company": analysis["company"],
            "opportunity_score": analysis["opportunity_score"],
            "summary": draft["executive_summary"],
            "key_findings": draft["key_findings"],
            "strengths": analysis["strengths"],
            "risks": analysis["risks"],
            "recommended_next_steps": draft["recommended_next_steps"],
            "validation": {
                "valid": validation["valid"],
                "confidence": validation["confidence"],
                "issues": validation["issues"],
            },
            "sources": sources,
            "agents": [step["agent_name"] for step in state["plan"]],
            "revisions": state["revisions"],
            **({"memory_notes": draft["context_notes"]} if draft.get("context_notes") else {}),
            # M9: structured citations for the [K#] findings (validated against retrieval).
            **({"citations": draft["citations"]} if draft.get("citations") else {}),
        },
        "current_agent": TeamRole.SUPERVISOR.value,
    }


def propose_action(state: TeamState, runtime: Runtime[TeamRunContext]) -> dict:
    """Supervisor turns the validated result into at most one proposed business action."""
    context = runtime.context
    proposal = context.provider.propose_action(state["objective"], state.get("final_output"))
    if proposal is None:
        return {"proposed_action": None}
    if not isinstance(proposal.get("action_type"), str) or not isinstance(
        proposal.get("payload"), dict
    ):
        raise TeamExecutionError(
            "The supervisor proposed a malformed action.", code="invalid_action"
        )
    proposal = {"action_type": proposal["action_type"][:80], "payload": proposal["payload"]}
    context.recorder.action_proposed(context.team.supervisor, proposal)
    return {"proposed_action": proposal, "current_agent": TeamRole.SUPERVISOR.value}


def apply_policy(state: TeamState, runtime: Runtime[TeamRunContext]) -> dict:
    """Evaluate server policy. Nothing from the prompt, instructions or payload can change it."""
    context = runtime.context
    proposal = state["proposed_action"]
    validated = "final_output" in state and bool(
        (state.get("validation_result") or {}).get("valid")
    )
    policy = evaluate(proposal["action_type"], validated_result=validated)
    if policy.decision != Decision.DENY:
        try:
            proposal = {**proposal, "payload": validate_payload(**proposal)}
        except ValueError:
            policy = PolicyDecision(
                Decision.DENY,
                policy.risk_level,
                "m6.invalid_payload",
                "The proposed action payload is not valid.",
            )
    if policy.decision != Decision.REQUIRE_APPROVAL:
        context.recorder.policy_decided(context.team.supervisor, proposal, policy)
    return {"proposed_action": proposal, "policy_decision": policy.as_dict()}


def execute_action(state: TeamState, runtime: Runtime[TeamRunContext]) -> dict:
    return {"action_result": runtime.context.recorder.execute_action(state["proposed_action"])}


def request_approval(state: TeamState, runtime: Runtime[TeamRunContext]) -> dict:
    context = runtime.context
    recorded = state["policy_decision"]
    policy = PolicyDecision(
        Decision(recorded["decision"]),
        RiskLevel(recorded["risk_level"]),
        recorded["rule_key"],
        recorded["reason"],
    )
    approval_id = context.recorder.request_approval(
        context.team.supervisor, state["proposed_action"], policy
    )
    return {"approval_request_id": approval_id}


POLICY_ROUTES = {
    Decision.ALLOW.value: "execute_action",
    Decision.REQUIRE_APPROVAL.value: "request_approval",
    Decision.DENY.value: END,
}


def build_team_graph() -> StateGraph:
    graph = StateGraph(TeamState, context_schema=TeamRunContext)
    graph.add_node("supervisor_plan", supervised(supervisor_plan))
    graph.add_node("supervisor_review", supervised(supervisor_review))
    for role in AGENT_ROLES:
        graph.add_node(role, agent_node(role))
        graph.add_edge(role, "supervisor_review")
    graph.add_node(FINALIZE, finalize)
    for name, node in (
        ("propose_action", propose_action),
        ("apply_policy", apply_policy),
        ("execute_action", execute_action),
        ("request_approval", request_approval),
    ):
        graph.add_node(name, supervised(node))
    graph.add_edge(START, "supervisor_plan")
    graph.add_conditional_edges(
        "supervisor_plan",
        lambda state: "supervisor_review" if state["plan"] else "propose_action",
        ["supervisor_review", "propose_action"],
    )
    graph.add_conditional_edges(
        "supervisor_review", lambda state: state["next_agent"], [*AGENT_ROLES, FINALIZE]
    )
    # M6: policy only after content validation (finalize runs only on an approved draft).
    graph.add_edge(FINALIZE, "propose_action")
    graph.add_conditional_edges(
        "propose_action",
        lambda state: "apply_policy" if state.get("proposed_action") else END,
        ["apply_policy", END],
    )
    graph.add_conditional_edges(
        "apply_policy",
        lambda state: POLICY_ROUTES[state["policy_decision"]["decision"]],
        ["execute_action", "request_approval", END],
    )
    graph.add_edge("execute_action", END)
    graph.add_edge("request_approval", END)
    return graph


@cache
def compiled_team_graph() -> CompiledStateGraph:
    return build_team_graph().compile(name="nexusflow_agent_team")
