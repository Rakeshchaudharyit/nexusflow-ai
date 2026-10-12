"""`internal:knowledge_search`: hybrid retrieval over the sources granted to the calling agent.

The allowed source ids come from the server-built ToolExecutionContext (loaded at run start),
never from tool arguments: a `source_ids` argument can only narrow that set.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, sessionmaker

from app.agents.errors import ToolExecutionError
from app.agents.tools.base import ToolDefinition, ToolExecutionContext
from app.core.config import Settings
from app.knowledge.access import KNOWLEDGE_TOOL
from app.knowledge.embeddings import EmbeddingProvider
from app.knowledge.retrieval import Retrieval, search


class KnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500)
    source_ids: list[UUID] | None = Field(default=None, max_length=20)
    top_k: int | None = Field(default=None, ge=1, le=10)


def retrieval_output(retrieval: Retrieval) -> dict:
    return {
        "query": retrieval.query,
        "results": [
            {
                **hit.citation(),
                "semantic_score": hit.semantic_score,
                "lexical_score": hit.lexical_score,
            }
            for hit in retrieval.hits
        ],
        "sources_searched": retrieval.sources_searched,
        "candidates": retrieval.candidates,
        "truncated": retrieval.truncated,
        "insufficient": retrieval.insufficient,
    }


class KnowledgeSearchTool:
    definition = ToolDefinition(
        name=KNOWLEDGE_TOOL,
        description=(
            "Search the knowledge sources assigned to this agent (hybrid semantic + keyword "
            "retrieval) and return ranked excerpts with citations."
        ),
        input_model=KnowledgeSearchInput,
    )

    def __init__(
        self, sessions: sessionmaker[Session], settings: Settings, embedder: EmbeddingProvider
    ):
        self._sessions = sessions
        self._settings = settings
        self._embedder = embedder

    def execute(self, arguments: KnowledgeSearchInput, context: ToolExecutionContext) -> dict:
        allowed = list(context.knowledge_source_ids)
        if not allowed:
            raise ToolExecutionError(
                "No knowledge sources are assigned to this agent.", code="tool_not_permitted"
            )
        if arguments.source_ids is not None:
            if not set(arguments.source_ids) <= set(allowed):
                raise ToolExecutionError(
                    "The agent may only search its assigned knowledge sources.",
                    code="tool_not_permitted",
                )
            allowed = [source for source in allowed if source in set(arguments.source_ids)]
        with self._sessions() as db:
            retrieval = search(
                db,
                self._settings,
                self._embedder,
                organization_id=context.organization_id,
                query=arguments.query,
                source_ids=allowed,
                top_k=arguments.top_k,
            )
        return retrieval_output(retrieval)
