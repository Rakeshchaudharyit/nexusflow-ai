"""Tool spans: wraps the ToolResolver so every real tool call (internal, MCP, knowledge
search) is timed and summarized, nested under the node or agent that made it."""

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from app.agents.tools import ToolExecutionContext, ToolResolver, ToolResult
from app.models.observability import SpanStatus, SpanType
from app.observability.redact import arguments_summary, clip
from app.observability.tracer import Tracer


def knowledge_metadata(output: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    results = output.get("results") or []
    searched = output.get("sources_searched") or []
    return {
        "allowed_sources": len(context.knowledge_source_ids),
        "sources_searched": len(searched),
        "source_names": [item.get("source_name") for item in searched][:5],
        "candidates": output.get("candidates"),
        "results": len(results),
        "top_score": max((item.get("score", 0) for item in results), default=None),
        "context_chars": sum(len(item.get("excerpt", "")) for item in results),
        "truncated": bool(output.get("truncated")),
        "insufficient": bool(output.get("insufficient")),
        "documents": [item.get("document_name") for item in results][:5],
    }


class TracedResolver:
    """Same interface as ToolResolver; delegates and records one span per call."""

    def __init__(self, inner: ToolResolver, tracer: Tracer):
        self._inner = inner
        self._tracer = tracer

    def resolve(self, source: str, tool_name: str) -> str | None:
        return self._inner.resolve(source, tool_name)

    def execute(
        self, key: str, arguments: Mapping[str, Any], context: ToolExecutionContext | None
    ) -> ToolResult:
        name = key.rsplit(":", 1)[-1]
        span_type = (
            SpanType.MCP
            if key.startswith("mcp:")
            else SpanType.KNOWLEDGE_SEARCH
            if name == "knowledge_search"
            else SpanType.TOOL
        )
        summary = (
            f"query={clip((arguments or {}).get('query'), 120)}"
            if span_type == SpanType.KNOWLEDGE_SEARCH
            else arguments_summary(dict(arguments or {}))
        )
        span = self._tracer.open(span_type, name, tool_key=key, input_summary=summary)
        try:
            result = self._inner.execute(key, arguments, context)
        except Exception as error:
            details = getattr(error, "details", None) or {}
            span.fields["mcp_server_id"] = _uuid(details.get("server_id"))
            self._tracer.close(
                span,
                SpanStatus.FAILED,
                error_code=getattr(error, "code", "tool_execution_failed"),
                error_message=getattr(error, "message", None),
                metadata={
                    key: value
                    for key, value in details.items()
                    if key in ("server_name", "tool_name", "tool_type")
                },
            )
            raise
        metadata: dict[str, Any] = {"tool_type": result.tool_type}
        if span_type == SpanType.MCP:
            server_id = result.metadata.get("server_id")
            span.fields["mcp_server_id"] = _uuid(server_id)
            metadata |= {
                "server_name": result.metadata.get("server_name"),
                "tool_name": result.tool,
                "server_duration_ms": result.metadata.get("duration_ms"),
            }
            output_summary = f"keys: {', '.join(sorted(result.output)[:8])}"
        elif span_type == SpanType.KNOWLEDGE_SEARCH:
            metadata |= knowledge_metadata(result.output, context)
            searched = result.output.get("sources_searched") or []
            if len(searched) == 1:
                span.fields["knowledge_source_id"] = _uuid(searched[0].get("source_id"))
            output_summary = (
                f"{metadata['results']} results from {metadata['sources_searched']} sources"
            )
        else:
            output_summary = f"keys: {', '.join(sorted(result.output)[:8])}"
        self._tracer.close(span, output_summary=output_summary, metadata=metadata)
        return result


def _uuid(value) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None
