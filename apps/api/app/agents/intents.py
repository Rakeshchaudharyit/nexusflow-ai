"""Rule-based request classification.

M3 classifies intents with explicit rules so runs are reproducible offline. The rules are
ordered: arithmetic, a named demonstration customer, platform status, generic customer
wording, then the general fallback. Mentioning "MCP" selects the MCP variant of a tool; it
never selects a server, tenant or tool key.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.state import Intent, ToolSource
from app.agents.tools.customers import match_demo_customer

NUMBER = r"(-?\d{1,13}(?:\.\d{1,10})?)"
OPERATORS = {
    "plus": "add",
    "+": "add",
    "minus": "subtract",
    "-": "subtract",
    "times": "multiply",
    "multiplied by": "multiply",
    "x": "multiply",
    "*": "multiply",
    "×": "multiply",
    "divided by": "divide",
    "over": "divide",
    "/": "divide",
    "÷": "divide",
}
OPERATOR_PATTERN = "|".join(
    re.escape(symbol) for symbol in sorted(OPERATORS, key=len, reverse=True)
)
# Operands must stand alone so digits inside identifiers (UUIDs, SKUs) are not arithmetic.
ARITHMETIC = re.compile(
    rf"(?<![\w.-]){NUMBER}\s*({OPERATOR_PATTERN})\s*{NUMBER}(?![\w.]*\d)(?!\w)", re.IGNORECASE
)
SUBJECTS = r"\b(?:system|platform|services?|infrastructure)\b"
CONDITIONS = r"\b(?:status|health|healthy|ready|readiness)\b"
SYSTEM_STATUS = re.compile(
    rf"{SUBJECTS}.*{CONDITIONS}|{CONDITIONS}.*{SUBJECTS}|\bhealth\s*check\b", re.IGNORECASE
)
MCP_REQUEST = re.compile(r"\bmcp\b", re.IGNORECASE)
# Questions about a known account that thread memory can answer without a new lookup.
ACCOUNT_QUESTION = re.compile(
    r"\b(?:who\s+owns|owner|which\s+region|region|segment|account\s+status)\b", re.IGNORECASE
)
CUSTOMER_WORDING = re.compile(
    r"\b(?:look\s*up|lookup|find|search for)\s+(?:the\s+)?(?:customer\s+|account\s+)?"
    r"(?P<subject>[^.,;?!]+?)(?=\s+and\b|[.,;?!]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Classification:
    intent: Intent
    arguments: dict[str, Any] = field(default_factory=dict)
    tool_source: ToolSource = "internal"


def classify_request(text: str) -> Classification:
    classification = classify_intent(text)
    if MCP_REQUEST.search(text) and classification.intent != "general":
        return Classification(classification.intent, classification.arguments, "mcp")
    return classification


def recalls_memory(text: str, classification: Classification, known_account: bool) -> bool:
    """Memory only answers questions no tool rule claimed. It never selects or triggers a tool."""
    return (
        known_account
        and classification.intent == "general"
        and ACCOUNT_QUESTION.search(text) is not None
    )


# An explicit lookup request stays a customer lookup even when knowledge is available.
LOOKUP_VERB = re.compile(r"\b(?:look\s*up|lookup|find|search for)\b", re.IGNORECASE)


def wants_knowledge(text: str, classification: Classification) -> bool:
    """For an agent with knowledge access: questions no tool rule claimed, and questions that
    merely mention a demo customer (\"What security terms apply to Acme?\"), go to knowledge
    search. Arithmetic, platform status and explicit lookups keep their tools."""
    if classification.intent == "general":
        return True
    return classification.intent == "customer_lookup" and LOOKUP_VERB.search(text) is None


def classify_intent(text: str) -> Classification:
    if match := ARITHMETIC.search(text):
        left, symbol, right = match.groups()
        return Classification(
            "calculation",
            {"operation": OPERATORS[symbol.lower()], "left": left, "right": right},
        )
    if customer := match_demo_customer(text):
        return Classification("customer_lookup", {"query": customer["company"]})
    if SYSTEM_STATUS.search(text):
        return Classification("system_status", {})
    if match := CUSTOMER_WORDING.search(text):
        return Classification("customer_lookup", {"query": match.group("subject").strip()[:200]})
    return Classification("general", {})
