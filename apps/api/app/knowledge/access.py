"""Which knowledge sources a run may search.

An agent searches a source only with BOTH grants, loaded from the database at run start:
the `internal:knowledge_search` tool assignment (M5 agent_tools) and an enabled
agent_knowledge_sources row. Nothing in a prompt, document or memory can add either.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge import AgentKnowledgeSource
from app.models.teams import AgentTool

KNOWLEDGE_TOOL = "knowledge_search"
KNOWLEDGE_TOOL_KEY = f"internal:{KNOWLEDGE_TOOL}"


def granted_sources(
    db: Session, organization_id: UUID, agent_ids: list[UUID]
) -> dict[UUID, tuple[UUID, ...]]:
    if not agent_ids:
        return {}
    permitted = set(
        db.scalars(
            select(AgentTool.agent_id).where(
                AgentTool.organization_id == organization_id,
                AgentTool.agent_id.in_(agent_ids),
                AgentTool.tool_key == KNOWLEDGE_TOOL_KEY,
                AgentTool.is_enabled.is_(True),
            )
        )
    )
    grants: dict[UUID, list[UUID]] = {}
    for agent_id, source_id in db.execute(
        select(AgentKnowledgeSource.agent_id, AgentKnowledgeSource.source_id)
        .where(
            AgentKnowledgeSource.organization_id == organization_id,
            AgentKnowledgeSource.agent_id.in_(list(permitted)),
            AgentKnowledgeSource.is_enabled.is_(True),
        )
        .order_by(AgentKnowledgeSource.created_at, AgentKnowledgeSource.source_id)
    ):
        grants.setdefault(agent_id, []).append(source_id)
    return {agent_id: tuple(sources) for agent_id, sources in grants.items()}
