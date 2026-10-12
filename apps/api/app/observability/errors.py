"""Normalized error categories. The underlying safe error_code is always kept as well."""

CATEGORIES = (
    "validation",
    "permission",
    "tenant",
    "tool",
    "mcp",
    "knowledge",
    "policy",
    "approval",
    "worker",
    "provider",
    "cancelled",
    "internal",
)
EXACT = {
    "invalid_tool_arguments": "validation",
    "invalid_plan": "validation",
    "invalid_output": "validation",
    "invalid_action": "validation",
    "invalid_supervisor_decision": "validation",
    "objective_not_supported": "validation",
    "insufficient_context": "validation",
    "revision_limit_exceeded": "validation",
    "iteration_limit_exceeded": "validation",
    "team_not_runnable": "validation",
    "agent_not_active": "validation",
    "run_not_queued": "validation",
    "tool_not_permitted": "permission",
    "forbidden": "permission",
    "missing_execution_context": "tenant",
    "unknown_tool": "tool",
    "tool_execution_failed": "tool",
    "internal_tool_unavailable": "tool",
    "policy_denied": "policy",
    "action_failed": "approval",
    "worker_lost": "worker",
    "worker_error": "worker",
    "provider_timeout": "provider",
    "embedding_unavailable": "knowledge",
    "embedding_rejected": "knowledge",
    "cancelled": "cancelled",
}
PREFIXES = (
    ("mcp_", "mcp"),
    ("approval_", "approval"),
    ("knowledge_", "knowledge"),
    ("llm_", "provider"),
)


def categorize(code: str | None) -> str | None:
    if not code:
        return None
    if code in EXACT:
        return EXACT[code]
    for prefix, category in PREFIXES:
        if code.startswith(prefix):
            return category
    return "internal"
