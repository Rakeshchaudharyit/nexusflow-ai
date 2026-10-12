"""One place that assembles the agent and team runtimes, for the API (inline mode, tests) and
the worker process alike, so both execute identical code."""

from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.agents.providers import create_llm_provider
from app.agents.runtime import AgentRuntime
from app.agents.tools import ToolRegistry, build_demo_registry
from app.core.config import Settings
from app.knowledge.embeddings import create_embedder
from app.knowledge.ingestion import KnowledgeIngestor
from app.knowledge.storage import FileStore
from app.knowledge.tool import KnowledgeSearchTool
from app.mcp.adapter import McpToolProvider
from app.mcp.client import McpClient, McpTimeouts
from app.mcp.urls import UrlPolicy
from app.schemas.health import ReadinessResponse
from app.teams.provider import create_team_provider
from app.teams.runtime import TeamRuntime


def mcp_url_policy(settings: Settings) -> UrlPolicy:
    return UrlPolicy(
        allowed_hosts=frozenset(settings.mcp_allowed_hosts),
        allow_public_hosts=settings.mcp_allow_public_hosts,
    )


def mcp_client(settings: Settings) -> McpClient:
    return McpClient(
        mcp_url_policy(settings),
        McpTimeouts(
            connect_seconds=settings.mcp_connect_timeout_seconds,
            request_seconds=settings.mcp_request_timeout_seconds,
        ),
    )


def knowledge_store(settings: Settings) -> FileStore:
    return FileStore(settings.knowledge_upload_dir)


def internal_tools(
    probe: Callable[[], ReadinessResponse],
    sessions: sessionmaker[Session] | None = None,
    settings: Settings | None = None,
) -> ToolRegistry:
    """Internal tools; with a database, also knowledge_search (M9)."""
    extra = ()
    if sessions is not None and settings is not None:
        extra = (KnowledgeSearchTool(sessions, settings, create_embedder(settings)),)
    return build_demo_registry(probe, extra)


def knowledge_ingestor(settings: Settings, sessions: sessionmaker[Session]) -> KnowledgeIngestor:
    return KnowledgeIngestor(
        sessions, settings, create_embedder(settings), knowledge_store(settings)
    )


def tool_providers(sessions: sessionmaker[Session], mcp: McpClient) -> dict:
    return {"mcp": lambda context: McpToolProvider(sessions, mcp, context)}


def agent_runtime(
    settings: Settings, sessions: sessionmaker[Session], tools: ToolRegistry, mcp: McpClient
) -> AgentRuntime:
    return AgentRuntime(
        sessions=sessions,
        tools=tools,
        llm=create_llm_provider(settings),
        providers=tool_providers(sessions, mcp),
        memory_settings=settings,
    )


def team_runtime(
    settings: Settings, sessions: sessionmaker[Session], tools: ToolRegistry, mcp: McpClient
) -> TeamRuntime:
    return TeamRuntime(
        sessions=sessions,
        tools=tools,
        provider=create_team_provider(settings),
        providers=tool_providers(sessions, mcp),
        approval_expire_hours=settings.approval_expire_hours,
        memory_settings=settings,
    )
