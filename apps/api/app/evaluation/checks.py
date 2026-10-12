"""Deterministic checks. Each check is named for exactly what it verifies; nothing here
judges semantics or general factual accuracy.

    expected_status            the run's final status
    expected_intent            single-agent intent
    expected_tool              a tool (pattern) was called / "none": no tool call
    output_contains / excludes case-insensitive phrase presence in the answer text
    expected_value:<path>      a field of the final output equals a value
    policy_decision / action_type / no_action_executed
    no_match_response          the insufficient-knowledge answer, with no citations
    citation_ids_valid         every [K#] in the answer has a structured citation
    citations_map_to_chunks    every citation is a retrieved chunk that exists in the database
    expected_document_cited    an expected document is cited
    no_unrelated_citation      only expected documents are cited
    retrieval_hit_at_k         an expected document is in the top-K retrieved (Hit@K)
    cited_excerpt_contains     (limited groundedness) each expected phrase appears in a cited
                               excerpt, i.e. the claim is backed by quoted retrieved text
"""

import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from app.knowledge.context import INSUFFICIENT
from app.models.evaluation import EvaluationCase

CITATION = re.compile(r"\[(K\d+)\]")


@dataclass
class Observation:
    """What actually happened, gathered from the persisted run (never from the case)."""

    kind: str  # agent | team
    status: str
    text: str = ""
    intent: str | None = None
    tools: list[str] = field(default_factory=list)
    final_output: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    existing_chunks: set[str] = field(default_factory=set)
    policy_decision: str | None = None
    action_type: str | None = None
    executions: int = 0
    error_code: str | None = None

    def summary(self) -> dict[str, Any]:
        """Bounded actual values stored with the result for display."""
        return {
            "status": self.status,
            "intent": self.intent,
            "tools": self.tools[:10],
            "text": self.text[:600],
            "policy_decision": self.policy_decision,
            "action_type": self.action_type,
            "executions": self.executions,
            "error_code": self.error_code,
            "cited_documents": sorted({c.get("document_name") for c in self.citations}),
            "retrieved": [
                {
                    "rank": index,
                    "citation_id": item.get("citation_id"),
                    "document_name": item.get("document_name"),
                    "page": item.get("page"),
                    "score": item.get("score"),
                }
                for index, item in enumerate(self.retrieved[:10], start=1)
            ],
        }


def lookup(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def equal(left: Any, right: Any) -> bool:
    if (
        isinstance(left, int | float)
        and isinstance(right, int | float)
        and not (isinstance(left, bool) or isinstance(right, bool))
    ):
        return abs(left - right) < 1e-9
    return left == right


def check(name: str, passed: bool, expected: Any, actual: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "expected": expected, "actual": actual}


def run_checks(case: EvaluationCase, observed: Observation) -> tuple[list[dict], dict[str, Any]]:
    """Return (checks, retrieval metrics). Only expectations that are set become checks."""
    checks: list[dict] = []
    metrics: dict[str, Any] = {}
    text = observed.text.casefold()
    if case.expected_status:
        checks.append(
            check(
                "expected_status",
                observed.status == case.expected_status,
                case.expected_status,
                observed.status,
            )
        )
    if case.expected_intent:
        checks.append(
            check(
                "expected_intent",
                observed.intent == case.expected_intent,
                case.expected_intent,
                observed.intent,
            )
        )
    if case.expected_tool_key:
        if case.expected_tool_key == "none":
            passed = not observed.tools
        else:
            passed = any(fnmatchcase(tool, case.expected_tool_key) for tool in observed.tools)
        checks.append(check("expected_tool", passed, case.expected_tool_key, observed.tools))
    for phrase in case.expected_output_contains or []:
        checks.append(check(f"output_contains:{phrase}", phrase.casefold() in text, phrase, None))
    for phrase in case.expected_output_excludes or []:
        checks.append(
            check(f"output_excludes:{phrase}", phrase.casefold() not in text, phrase, None)
        )
    for path, value in (case.expected_values or {}).items():
        actual = lookup(observed.final_output, path)
        checks.append(check(f"expected_value:{path}", equal(actual, value), value, actual))
    if case.expected_policy_decision:
        checks.append(
            check(
                "policy_decision",
                observed.policy_decision == case.expected_policy_decision,
                case.expected_policy_decision,
                observed.policy_decision,
            )
        )
        if case.expected_policy_decision in ("deny", "require_approval", "none"):
            checks.append(
                check("no_action_executed", observed.executions == 0, 0, observed.executions)
            )
    if case.expected_action_type:
        checks.append(
            check(
                "action_type",
                observed.action_type == case.expected_action_type,
                case.expected_action_type,
                observed.action_type,
            )
        )
    if case.expected_no_match:
        checks.append(
            check(
                "no_match_response",
                observed.text.strip() == INSUFFICIENT and not observed.citations,
                INSUFFICIENT,
                observed.text[:200],
            )
        )
    expected_documents = set(case.expected_citation_documents or [])
    if expected_documents:
        used = CITATION.findall(observed.text)
        for finding in observed.final_output.get("key_findings", []) or []:
            used += CITATION.findall(str(finding))
        cited_ids = {citation.get("citation_id") for citation in observed.citations}
        checks.append(
            check(
                "citation_ids_valid",
                bool(used) and set(used) <= cited_ids,
                "every [K#] has a citation",
                sorted(set(used) - cited_ids) or sorted(set(used)),
            )
        )
        retrieved_chunks = {item.get("chunk_id") for item in observed.retrieved}
        mapped = all(
            citation.get("chunk_id") in retrieved_chunks
            and citation.get("chunk_id") in observed.existing_chunks
            for citation in observed.citations
        )
        checks.append(
            check(
                "citations_map_to_chunks",
                bool(observed.citations) and mapped,
                "retrieved, existing chunks",
                len(observed.citations),
            )
        )
        cited_documents = {citation.get("document_name") for citation in observed.citations}
        checks.append(
            check(
                "expected_document_cited",
                bool(cited_documents & expected_documents),
                sorted(expected_documents),
                sorted(cited_documents),
            )
        )
        checks.append(
            check(
                "no_unrelated_citation",
                bool(cited_documents) and cited_documents <= expected_documents,
                sorted(expected_documents),
                sorted(cited_documents - expected_documents),
            )
        )
        k = max(1, case.retrieval_k or 5)
        rank = next(
            (
                index
                for index, item in enumerate(observed.retrieved, start=1)
                if item.get("document_name") in expected_documents
            ),
            None,
        )
        hit = rank is not None and rank <= k
        metrics = {
            "hit_at_k": hit,
            "k": k,
            "rank": rank,
            "reciprocal_rank": 1 / rank if rank else 0,
        }
        checks.append(check("retrieval_hit_at_k", hit, f"top {k}", rank))
        excerpts = " ".join(str(c.get("excerpt", "")) for c in observed.citations).casefold()
        for phrase in case.expected_output_contains or []:
            checks.append(
                check(
                    f"cited_excerpt_contains:{phrase}",
                    phrase.casefold() in excerpts,
                    phrase,
                    None,
                )
            )
    return checks, metrics


def score(checks: list[dict]) -> float:
    return round(sum(1 for item in checks if item["passed"]) / len(checks), 4) if checks else 0.0
