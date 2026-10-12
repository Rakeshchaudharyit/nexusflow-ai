"""Reasoning steps of a team, behind a provider interface.

`DeterministicTeamProvider` is the M5 default: rule-based, reproducible and offline, like the
M3 `DeterministicLLMProvider`. A model-backed provider would implement the same protocol. The
graph, not the provider, enforces which decisions are legal, so a misbehaving provider cannot
skip validation, loop forever or reach agents outside the team.
"""

import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.actions.proposals import propose_action
from app.agents.tools.customers import match_demo_customer
from app.core.config import Settings
from app.knowledge.context import claim
from app.teams.errors import TeamExecutionError

COMPANY_IN_OBJECTIVE = re.compile(
    r"\b(?:analy[sz]e|assess|evaluate|research|review)\s+"
    r"(?P<company>[A-Z][\w&'.-]*(?:\s+[A-Z][\w&'.-]*){0,4})"
)
MAX_SUMMARY = 600
MAX_LIST = 8
MAX_KNOWLEDGE_FINDINGS = 2
CITATION = re.compile(r"\[(K\d+)\]")


def knowledge_finding(passage: dict[str, Any]) -> str:
    return f"Knowledge: {claim(passage['excerpt'])} [{passage['citation_id']}]"


@dataclass(frozen=True)
class SupervisorView:
    """What the supervisor sees when choosing the next step."""

    plan_roles: list[str]
    completed: list[str]
    failed: list[str]
    legal: list[str]
    has_draft: bool
    draft_valid: bool | None
    revisions: int


class TeamProvider(Protocol):
    name: str

    def plan(self, objective: str, roster: list[dict]) -> dict[str, Any]: ...

    def decide(self, view: SupervisorView) -> str: ...

    def analyze(self, task: dict[str, Any]) -> dict[str, Any]: ...

    def write(self, task: dict[str, Any]) -> dict[str, Any]: ...

    def validate(self, task: dict[str, Any]) -> dict[str, Any]: ...

    def propose_action(
        self, objective: str, result: dict[str, Any] | None
    ) -> dict[str, Any] | None: ...


def extract_company(objective: str) -> str | None:
    if record := match_demo_customer(objective):
        return record["company"]
    match = COMPANY_IN_OBJECTIVE.search(objective)
    return match.group("company").strip() if match else None


TASKS = {
    "customer_specialist": "Retrieve account context for {company}.",
    "researcher": "Identify demonstration research signals for {company}.",
    "analyst": "Assess {company} as an opportunity from the customer and research findings.",
    "writer": "Draft a concise recommendation for {company} addressing the objective.",
    "validator": "Verify the draft is complete and grounded in the team's findings.",
}


def grounding_issues(task: dict[str, Any]) -> list[str]:
    """Deterministic checks that the draft only states facts found earlier in the run."""
    draft = task["draft"]
    customer = task.get("customer_context") or {}
    research = task.get("research_context") or {}
    analysis = task.get("analysis_context") or {}
    issues = []
    for section in ("title", "executive_summary", "key_findings", "recommended_next_steps"):
        if not draft.get(section):
            issues.append(f"missing section: {section}")
    if len(draft.get("executive_summary", "")) > MAX_SUMMARY:
        issues.append("executive_summary exceeds the length limit")
    for section in ("key_findings", "recommended_next_steps"):
        if len(draft.get(section, [])) > MAX_LIST:
            issues.append(f"{section} has too many items")
    known = {
        "company": analysis.get("company"),
        "opportunity_score": analysis.get("opportunity_score"),
    }
    if customer.get("found"):
        known |= {key: customer.get(key) for key in ("segment", "status", "account_owner")}
    for fact, value in (draft.get("facts") or {}).items():
        if fact not in known or known[fact] != value:
            issues.append(f"unsupported fact: {fact}")
    for signal in draft.get("cited_signals", []):
        if signal not in research.get("signals", []):
            issues.append(f"unsupported research signal: {signal}")
    # M9: every [K#] must be a retrieved passage, quoted as retrieved.
    retrieved = {
        item["citation_id"]: item for item in (research.get("knowledge") or {}).get("results", [])
    }
    for finding in draft.get("key_findings", []):
        for citation_id in CITATION.findall(finding):
            passage = retrieved.get(citation_id)
            if passage is None or finding != knowledge_finding(passage):
                issues.append(f"unsupported citation: {citation_id}")
    for citation in draft.get("citations", []):
        if retrieved.get(citation.get("citation_id")) != citation:
            issues.append(f"unsupported citation: {citation.get('citation_id')}")
    action = analysis.get("recommended_action")
    if action and action not in draft.get("recommended_next_steps", []):
        issues.append("missing key result: recommended action")
    return issues


class DeterministicTeamProvider:
    name = "deterministic"

    def plan(self, objective: str, roster: list[dict]) -> dict[str, Any]:
        company = extract_company(objective)
        if company is None:
            raise TeamExecutionError(
                "The objective does not name a company the team can analyze.",
                code="objective_not_supported",
            )
        return {
            "company": company,
            "steps": [
                {"role": member["role"], "task": TASKS[member["role"]].format(company=company)}
                for member in roster
                if member["role"] in TASKS
            ],
        }

    def decide(self, view: SupervisorView) -> str:
        # Follow the plan: specialists in order, then writer, validator and finalize.
        pending = [role for role in view.plan_roles if role in view.legal]
        return pending[0] if pending else view.legal[0]

    def analyze(self, task: dict[str, Any]) -> dict[str, Any]:
        customer = task.get("customer_context") or {}
        research = task.get("research_context") or {}
        if not customer.get("found") and not research.get("signals"):
            raise TeamExecutionError(
                "The analyst has no customer or research findings to assess.",
                code="insufficient_context",
            )
        company = customer.get("company") or research.get("company") or task["company"]
        score = 50
        strengths, risks = [], []
        segment = customer.get("segment")
        score += {"Enterprise": 20, "Mid-Market": 12, "SMB": 5}.get(segment, 0)
        if segment == "Enterprise":
            strengths.append("Enterprise segment account")
        status = customer.get("status")
        score += {"active": 10, "onboarding": 5, "at_risk": -10}.get(status, 0)
        if status == "active":
            strengths.append("Active relationship with a named account owner")
        elif status == "at_risk":
            risks.append("Account is currently at risk")
        elif status == "onboarding":
            risks.append("Account is still onboarding")
        if not customer.get("found"):
            risks.append("No customer record in the demonstration dataset")
        signals = research.get("signals", [])
        score += 4 * min(len(signals), 3)
        strengths.extend(signals[:3])
        if not signals:
            risks.append("No demonstration research signals")
        risks.append("Assessment relies on synthetic demonstration data")
        score = max(0, min(100, score))
        if score >= 75:
            action = (
                f"Schedule an executive discovery session for {company} with the account "
                "owner to scope an automation proposal."
            )
        elif score >= 50:
            action = f"Run a qualification call with {company} before committing resources."
        else:
            action = f"Keep {company} in nurture and revisit next quarter."
        return {
            "company": company,
            "opportunity_score": score,
            "strengths": strengths,
            "risks": risks,
            "recommended_action": action,
        }

    def write(self, task: dict[str, Any]) -> dict[str, Any]:
        analysis = task["analysis_context"]
        customer = task.get("customer_context") or {}
        research = task.get("research_context") or {}
        company = analysis["company"]
        facts: dict[str, Any] = {
            "company": company,
            "opportunity_score": analysis["opportunity_score"],
        }
        findings = []
        if customer.get("found"):
            facts |= {key: customer[key] for key in ("segment", "status", "account_owner")}
            findings += [
                f"Segment: {customer['segment']}",
                f"Account status: {customer['status'].replace('_', ' ')}",
                f"Account owner: {customer['account_owner']}",
            ]
        signals = research.get("signals", [])[:3]
        findings += [f"Research signal: {signal}" for signal in signals]
        # M9: retrieved knowledge, quoted with its citation id; nothing uncited is added.
        passages = (research.get("knowledge") or {}).get("results", [])[:MAX_KNOWLEDGE_FINDINGS]
        findings += [knowledge_finding(passage) for passage in passages]
        return {
            "title": f"{company}: opportunity assessment",
            "executive_summary": (
                f"{company} scores {analysis['opportunity_score']}/100 as an opportunity. "
                f"{analysis['recommended_action']}"
            )[:MAX_SUMMARY],
            "key_findings": findings[:MAX_LIST],
            "recommended_next_steps": [
                analysis["recommended_action"],
                "Confirm automation priorities and decision makers.",
                "Validate demonstration findings against real account data before outreach.",
            ],
            "facts": facts,
            "cited_signals": signals,
            **({"citations": passages} if passages else {}),
            # Remembered context is labelled as such, never presented as a validated fact.
            **(
                {"context_notes": list(task["memory_notes"])[:3]}
                if task.get("memory_notes")
                else {}
            ),
        }

    def validate(self, task: dict[str, Any]) -> dict[str, Any]:
        issues = grounding_issues(task)
        return {
            "valid": not issues,
            "issues": issues,
            "confidence": 0.95 if not issues else round(max(0.2, 0.95 - 0.25 * len(issues)), 2),
        }

    def propose_action(
        self, objective: str, result: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        return propose_action(objective, result)


def create_team_provider(settings: Settings) -> TeamProvider:
    if settings.llm_provider == "deterministic":
        return DeterministicTeamProvider()
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")
