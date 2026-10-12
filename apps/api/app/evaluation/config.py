"""What was evaluated: a safe configuration snapshot of each target and a deterministic hash.

Only configuration is included (names, status, flags, tool keys, knowledge sources and the
versions/checksums of their documents, and a SHA-256 of agent instructions). No secrets, no
document text and no memory. The same configuration always produces the same hash.
"""

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.agents import Agent
from app.models.knowledge import AgentKnowledgeSource, KnowledgeDocument, KnowledgeSource
from app.models.teams import AgentTeam, AgentTeamMember, AgentTool


def digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def agent_config(db: Session, organization_id: UUID, agent_id: UUID) -> dict[str, Any] | None:
    agent = db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.organization_id == organization_id)
    )
    if agent is None:
        return None
    tools = sorted(
        db.scalars(
            select(AgentTool.tool_key).where(
                AgentTool.organization_id == organization_id,
                AgentTool.agent_id == agent.id,
                AgentTool.is_enabled.is_(True),
            )
        )
    )
    knowledge = []
    for source in db.scalars(
        select(KnowledgeSource)
        .join(
            AgentKnowledgeSource,
            (AgentKnowledgeSource.source_id == KnowledgeSource.id)
            & (AgentKnowledgeSource.organization_id == KnowledgeSource.organization_id),
        )
        .where(
            AgentKnowledgeSource.organization_id == organization_id,
            AgentKnowledgeSource.agent_id == agent.id,
            AgentKnowledgeSource.is_enabled.is_(True),
        )
        .order_by(KnowledgeSource.id)
    ):
        documents = [
            [name, version, checksum[:16]]
            for name, version, checksum in db.execute(
                select(
                    KnowledgeDocument.name,
                    KnowledgeDocument.ingested_version,
                    KnowledgeDocument.checksum,
                )
                .where(KnowledgeDocument.source_id == source.id)
                .order_by(KnowledgeDocument.name)
            )
        ]
        knowledge.append(
            {
                "source_id": str(source.id),
                "name": source.name,
                "status": source.status.value,
                "embedding": f"{source.embedding_provider}/{source.embedding_model}",
                "documents": documents,
            }
        )
    config = {
        "id": str(agent.id),
        "name": agent.name,
        "status": agent.status.value,
        "instructions_sha256": hashlib.sha256(agent.instructions.encode()).hexdigest(),
        "workspace_memory_enabled": agent.workspace_memory_enabled,
        "tools": tools,
        "knowledge": knowledge,
    }
    return {**config, "config_hash": digest(config)}


def team_config(db: Session, organization_id: UUID, team_id: UUID) -> dict[str, Any] | None:
    team = db.scalar(
        select(AgentTeam).where(
            AgentTeam.id == team_id, AgentTeam.organization_id == organization_id
        )
    )
    if team is None:
        return None
    members = []
    for member in db.scalars(
        select(AgentTeamMember)
        .where(
            AgentTeamMember.team_id == team.id,
            AgentTeamMember.organization_id == organization_id,
        )
        .order_by(AgentTeamMember.position, AgentTeamMember.role)
    ):
        agent = agent_config(db, organization_id, member.agent_id) or {}
        members.append(
            {
                "role": member.role.value,
                "position": member.position,
                "is_required": member.is_required,
                "agent_id": str(member.agent_id),
                "agent_name": agent.get("name"),
                "agent_config_hash": agent.get("config_hash"),
            }
        )
    config = {
        "id": str(team.id),
        "name": team.name,
        "status": team.status.value,
        "workspace_memory_enabled": team.workspace_memory_enabled,
        "members": members,
    }
    return {**config, "config_hash": digest(config)}


def snapshot(
    db: Session,
    settings: Settings,
    organization_id: UUID,
    agent_ids: set[UUID],
    team_ids: set[UUID],
) -> tuple[dict[str, Any], str]:
    agents = {
        str(agent_id): config
        for agent_id in sorted(agent_ids, key=str)
        if (config := agent_config(db, organization_id, agent_id))
    }
    teams = {
        str(team_id): config
        for team_id in sorted(team_ids, key=str)
        if (config := team_config(db, organization_id, team_id))
    }
    data = {
        "agents": agents,
        "teams": teams,
        "llm_provider": settings.llm_provider,
        "embedding": {
            "provider": settings.knowledge_embedding_provider,
            "model": settings.knowledge_embedding_model,
            "dimension": settings.knowledge_embedding_dimension,
        },
        "app_version": settings.app_version,
    }
    return data, digest(data)
