"""Server-defined action policy.

Policy answers "may this business action run without a human?". It is separate from tool
permissions (agent_tools), which answer "may this agent call this tool?". Rules live only
here: prompts, agent instructions and action payloads are never inputs to the decision.
"""

from dataclasses import asdict, dataclass
from enum import StrEnum


class Decision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    risk_level: RiskLevel
    rule_key: str
    reason: str

    def as_dict(self) -> dict:
        return {key: str(value) for key, value in asdict(self).items()}


RULES: dict[str, tuple[Decision, RiskLevel, str]] = {
    "create_crm_note": (
        Decision.ALLOW,
        RiskLevel.LOW,
        "Internal demonstration CRM notes may run automatically.",
    ),
    "send_followup_email": (
        Decision.REQUIRE_APPROVAL,
        RiskLevel.MEDIUM,
        "Customer-facing communication requires human approval.",
    ),
    "update_opportunity_stage": (
        Decision.REQUIRE_APPROVAL,
        RiskLevel.MEDIUM,
        "Pipeline changes require human approval.",
    ),
    "delete_record": (Decision.DENY, RiskLevel.HIGH, "Record deletion is prohibited."),
}


def evaluate(action_type: str, *, validated_result: bool) -> PolicyDecision:
    """Decide for an action type. Unknown actions and unvalidated work are denied."""
    rule = RULES.get(action_type)
    if rule is None:
        return PolicyDecision(
            Decision.DENY, RiskLevel.HIGH, "m6.unknown_action", "Unknown actions are prohibited."
        )
    decision, risk, reason = rule
    if decision != Decision.DENY and not validated_result:
        return PolicyDecision(
            Decision.DENY,
            risk,
            "m6.requires_validated_result",
            "Actions may only follow a result the validator approved.",
        )
    return PolicyDecision(decision, risk, f"m6.{action_type}", reason)
