"""Explicit retry classification. Anything not listed is a permanent failure."""

# Transient dependency failures: the same attempt may succeed later.
RETRYABLE_CODES = frozenset(
    {
        "mcp_unavailable",  # MCP server unreachable (stopped, restarting, network)
        "mcp_timeout",  # MCP server did not answer in time
        "provider_timeout",  # reserved for live LLM providers (not in M7)
        "worker_lost",  # the worker stopped heartbeating mid-attempt
        "worker_error",  # infrastructure fault around the run (e.g. a dropped DB connection)
        "embedding_unavailable",  # M9: embedding provider timeout, 5xx or rate limit
        "storage_unavailable",  # M9: upload volume temporarily unreadable
    }
)
# Kept explicit for documentation and tests; they are never retried.
PERMANENT_CODES = frozenset(
    {
        "policy_denied",
        "invalid_action",
        "invalid_tool_arguments",
        "tool_not_permitted",
        "unknown_tool",
        "objective_not_supported",
        "team_not_runnable",
        "agent_not_active",
        "mcp_tool_not_found",
        "mcp_tool_disabled",
        "mcp_server_disabled",
        "mcp_url_rejected",
        "mcp_tool_error",
        "mcp_malformed_result",
        "agent_execution_failed",
        "team_execution_failed",
        # M9 ingestion: the file itself is unacceptable; retrying cannot help.
        "unsupported_file",
        "invalid_file",
        "no_text",
        "unsafe_filename",
        "file_missing",
        "document_missing",
        "embedding_rejected",
        "ingestion_failed",
    }
)
MAX_RETRY_DELAY_SECONDS = 300.0


def is_retryable(code: str | None) -> bool:
    return code in RETRYABLE_CODES


def retry_delay(failed_attempt: int, base_seconds: float) -> float:
    """Bounded exponential backoff: base, 3x base, 9x base... (5s, 15s with the defaults)."""
    return min(base_seconds * 3 ** max(failed_attempt - 1, 0), MAX_RETRY_DELAY_SECONDS)
