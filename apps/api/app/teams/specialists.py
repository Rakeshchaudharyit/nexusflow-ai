"""Work performed by each team role.

Every function receives only its minimized task input (never the shared state) and returns a
structured output plus the tool calls it made. Specialists never call each other; results go
back through the supervisor.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agents.tools import ToolResult
from app.teams.errors import TeamExecutionError
from app.teams.provider import TeamProvider
from app.teams.research import research_signals
from app.teams.toolbox import AgentToolbox


@dataclass
class AgentWork:
    output: dict[str, Any]
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AgentTask:
    input: dict[str, Any]
    instructions: str  # untrusted; may shape wording, never tools or tenancy
    toolbox: AgentToolbox
    provider: TeamProvider


CITATION_FIELDS = (
    "citation_id",
    "source_id",
    "source_name",
    "document_id",
    "document_name",
    "chunk_id",
    "chunk_index",
    "page",
    "section",
    "excerpt",
    "score",
)


def tool_call(result: ToolResult) -> dict[str, Any]:
    return {
        "tool_key": result.tool_key,
        "tool_type": result.tool_type,
        "tool": result.tool,
        **{key: result.metadata.get(key) for key in ("server_id", "server_name", "duration_ms")},
    }


def customer_specialist(task: AgentTask) -> AgentWork:
    company = task.input["company"]
    key = task.toolbox.first_named("customer_lookup", "search_customer")
    if key is None:
        raise TeamExecutionError(
            "The customer specialist has no customer lookup tool assigned.",
            code="tool_not_permitted",
        )
    arguments = {"query": company} if key.startswith("internal:") else {"company": company}
    result = task.toolbox.call(key, arguments)
    output = result.output
    # Internal results nest the record; the MCP demo server returns it flat.
    record = output.get("customer", output) if output.get("found") else {}
    return AgentWork(
        output={
            "company": record.get("company", company),
            "found": bool(output.get("found")),
            "segment": record.get("segment"),
            "status": record.get("status"),
            "account_owner": record.get("account_owner"),
            "region": record.get("region"),
            "source": output.get("source") or output.get("data_source") or "demonstration",
            "tool_key": result.tool_key,
        },
        tool_calls=[tool_call(result)],
    )


def researcher(task: AgentTask) -> AgentWork:
    """Demonstration signals, plus (M9) the member's knowledge sources when it holds the
    knowledge_search tool. Only bounded, cited passages go back to the supervisor."""
    output = research_signals(task.input["company"])
    key = task.toolbox.first_named("knowledge_search")
    if key is None or not task.toolbox.knowledge_sources:
        return AgentWork(output=output)
    result = task.toolbox.call(key, {"query": task.input["objective"][:500]})
    knowledge = result.output
    output["knowledge"] = {
        "query": knowledge["query"],
        "results": [
            {name: item[name] for name in CITATION_FIELDS if name in item}
            for item in knowledge["results"]
        ],
        "sources_searched": knowledge["sources_searched"],
    }
    return AgentWork(output=output, tool_calls=[tool_call(result)])


def analyst(task: AgentTask) -> AgentWork:
    return AgentWork(output=task.provider.analyze(task.input))


def writer(task: AgentTask) -> AgentWork:
    return AgentWork(output=task.provider.write(task.input))


def validator(task: AgentTask) -> AgentWork:
    result = task.provider.validate(task.input)
    if not isinstance(result.get("valid"), bool) or not isinstance(result.get("issues"), list):
        raise TeamExecutionError("The validator returned an invalid result.", code="invalid_output")
    return AgentWork(output=result)


WORK: dict[str, Callable[[AgentTask], AgentWork]] = {
    "customer_specialist": customer_specialist,
    "researcher": researcher,
    "analyst": analyst,
    "writer": writer,
    "validator": validator,
}
