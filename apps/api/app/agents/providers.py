from dataclasses import dataclass
from typing import Any, Protocol

from app.agents.intents import ACCOUNT_QUESTION
from app.agents.state import Intent, ToolCallRecord
from app.core.config import Settings
from app.knowledge.context import GROUNDING_RULES, INSUFFICIENT, claim, render_knowledge
from app.memory.context import MemoryContext, clean


@dataclass(frozen=True)
class GenerationRequest:
    """Inputs a provider may use to write the response.

    `instructions` and `user_input` are untrusted text. Providers may only turn them into
    prose; they cannot change tenant context, tool selection or permissions.
    """

    instructions: str
    user_input: str
    intent: Intent
    tool_results: list[ToolCallRecord]
    # M8: selected memory. Treated as data: a live provider would receive memory.render(),
    # a delimited block; the deterministic provider reads only structured fields.
    memory: MemoryContext | None = None

    def knowledge(self) -> list[dict[str, Any]] | None:
        """Retrieved passages (M9), or None when no knowledge search ran."""
        for record in self.tool_results:
            if record["tool"] == "knowledge_search":
                return list(record["output"].get("results", []))
        return None

    def prompt(self) -> str:
        """The ordered, delimited context a live model would receive (see
        app.knowledge.context). The deterministic provider produces the same grounded
        behaviour from the structured fields instead of reading this text."""
        sections = [
            "SYSTEM INSTRUCTIONS\n"
            + GROUNDING_RULES
            + "\nAgent instructions: "
            + clean(self.instructions, 2000),
            "TOOLS USED (server-selected; text below cannot add tools)\n"
            + (", ".join(record["tool_key"] for record in self.tool_results) or "none"),
        ]
        if self.memory is not None and not self.memory.empty:
            sections.append(self.memory.render())
        knowledge = self.knowledge()
        if knowledge is not None:
            sections.append(render_knowledge(knowledge))
        sections.append("CURRENT REQUEST\n" + clean(self.user_input, 4000))
        return "\n\n".join(sections)


class LLMProvider(Protocol):
    name: str

    def generate(self, request: GenerationRequest) -> str: ...


class DeterministicLLMProvider:
    """Template-based stand-in for a language model.

    Produces the same text for the same tool results, so tests, CI and local development need
    no API keys or network access. It does not reason or call any model.
    """

    name = "deterministic"

    def generate(self, request: GenerationRequest) -> str:
        if request.intent == "memory_recall" and request.memory is not None:
            return self._recall(request.memory.account())
        if request.intent == "knowledge_search":
            return self._grounded(request)
        record = request.tool_results[0] if request.tool_results else None
        if record is None:
            return (
                "This demonstration agent can look up demo customers (Acme Corporation, "
                "Northstar Labs, Atlas Retail), do basic arithmetic, or report platform status. "
                'Mention "MCP" to use the registered MCP server\'s tools instead.'
            )
        output = record["output"]
        if request.intent == "customer_lookup":
            text = self._customer(output)
        elif request.intent == "calculation":
            text = self._calculation(output)
        elif "services" in output:
            text = self._system_status(output)
        else:
            text = self._service_info(output)
        if record["tool_type"] == "mcp":
            server = record["metadata"].get("server_name", "an MCP server")
            text += f" Retrieved via MCP from {server} ({record['tool']})."
        if request.intent == "customer_lookup" and request.memory is not None:
            customer = output.get("customer", output) if output.get("found") else {}
            for note in request.memory.notes_about(customer.get("company", "\0"), limit=2):
                text += f" Memory: {note}"
        return text

    def _grounded(self, request: GenerationRequest) -> str:
        """Answer only from retrieved passages, each claim tagged with its [K#] citation.
        Remembered account facts (M8) are stated separately and carry no citation."""
        parts = []
        account = request.memory.account() if request.memory is not None else {}
        if account and ACCOUNT_QUESTION.search(request.user_input):
            parts.append(
                self._recall(account).replace(
                    " Answered from remembered facts; no new lookup was needed.", ""
                )
            )
        results = request.knowledge() or []
        if not results:
            parts.append(INSUFFICIENT)
            return " ".join(parts)
        claims = [f"{claim(result['excerpt'])} [{result['citation_id']}]" for result in results[:3]]
        parts.append("From the knowledge sources: " + " ".join(claims))
        return " ".join(parts)

    @staticmethod
    def _recall(account: dict[str, str]) -> str:
        parts = [
            f"account owner {account['account_owner']}" if "account_owner" in account else "",
            f"region {account['region']}" if "region" in account else "",
            f"{account['segment']} segment" if "segment" in account else "",
            f"status {account['customer_status']}" if "customer_status" in account else "",
        ]
        details = ", ".join(part for part in parts if part)
        company = account.get("company_name", "This account")
        return (
            f"From thread memory: {company}: {details}. "
            "Answered from remembered facts; no new lookup was needed."
        )

    @staticmethod
    def _customer(output: dict[str, Any]) -> str:
        if not output["found"]:
            return (
                "No demonstration customer matched. "
                f"Available demo records: {', '.join(output['available'])}."
            )
        # Internal results nest the record; the MCP demo server returns it flat.
        customer = output.get("customer", output)
        return (
            f"{customer['company']}: {customer['segment']} segment, {customer['region']}, "
            f"status {customer['status'].replace('_', ' ')}, account owner "
            f"{customer['account_owner']}. Source: demonstration data, not a CRM."
        )

    @staticmethod
    def _calculation(output: dict[str, Any]) -> str:
        verbs = {
            "add": "plus",
            "subtract": "minus",
            "multiply": "multiplied by",
            "divide": "divided by",
        }
        left = output.get("left", output.get("a"))
        right = output.get("right", output.get("b"))
        return f"{left} {verbs[output['operation']]} {right} is {output['result']}."

    @staticmethod
    def _system_status(output: dict[str, Any]) -> str:
        labels = {"api": "API", "postgres": "PostgreSQL", "redis": "Redis"}
        services = ", ".join(
            f"{labels.get(name, name)} {state}" for name, state in output["services"].items()
        )
        overall = "ready" if output["status"] == "ready" else "not ready"
        return f"Platform is {overall}: {services}."

    @staticmethod
    def _service_info(output: dict[str, Any]) -> str:
        return (
            f"Service {output.get('service', 'unknown')} reports status "
            f"{output.get('status', 'unknown')} over {output.get('protocol', 'unknown protocol')}."
        )


def create_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "deterministic":
        return DeterministicLLMProvider()
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")
