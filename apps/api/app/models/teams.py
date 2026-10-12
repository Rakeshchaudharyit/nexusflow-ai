import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.agents import JSONDocument, RunStatus, string_enum
from app.models.identity import Timestamps


class TeamStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class TeamRole(StrEnum):
    """Orchestration roles inside a team. Unrelated to organization RBAC roles."""

    SUPERVISOR = "supervisor"
    RESEARCHER = "researcher"
    CUSTOMER_SPECIALIST = "customer_specialist"
    ANALYST = "analyst"
    WRITER = "writer"
    VALIDATOR = "validator"


SPECIALIST_ROLES = (TeamRole.CUSTOMER_SPECIALIST, TeamRole.RESEARCHER, TeamRole.ANALYST)


class AgentTeam(Timestamps, Base):
    __tablename__ = "agent_teams"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_agent_teams_organization_slug"),
        UniqueConstraint("id", "organization_id", name="uq_agent_teams_id_organization"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(140))
    description: Mapped[str] = mapped_column(String(500), default="", server_default="")
    status: Mapped[TeamStatus] = mapped_column(
        string_enum(TeamStatus, "agent_team_status"),
        default=TeamStatus.DRAFT,
        server_default=TeamStatus.DRAFT.value,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    # M8: workspace memory reaches the team's supervisor only when explicitly enabled.
    workspace_memory_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )


class AgentTeamMember(Timestamps, Base):
    __tablename__ = "agent_team_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["agent_teams.id", "agent_teams.organization_id"],
            name="fk_agent_team_members_team_organization",
            ondelete="CASCADE",
        ),
        # A team can only contain agents from its own organization.
        ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_agent_team_members_agent_organization",
            ondelete="CASCADE",
        ),
        # Each role is filled once, so a team has at most one supervisor.
        UniqueConstraint("team_id", "role", name="uq_agent_team_members_team_role"),
        UniqueConstraint("team_id", "agent_id", name="uq_agent_team_members_team_agent"),
        CheckConstraint("position >= 0", name="ck_agent_team_members_position"),
        Index("ix_agent_team_members_agent_id", "agent_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    role: Mapped[TeamRole] = mapped_column(string_enum(TeamRole, "agent_team_role"))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class AgentTeamRun(Timestamps, Base):
    __tablename__ = "agent_team_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["agent_teams.id", "agent_teams.organization_id"],
            name="fk_agent_team_runs_team_organization",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", name="uq_agent_team_runs_id_organization"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_agent_team_runs_duration"
        ),
        CheckConstraint("step_count >= 0", name="ck_agent_team_runs_step_count"),
        ForeignKeyConstraint(
            ["thread_id", "organization_id"],
            ["memory_threads.id", "memory_threads.organization_id"],
            name="fk_agent_team_runs_thread_organization",
        ),
        ForeignKeyConstraint(
            ["evaluation_run_id", "organization_id"],
            ["evaluation_runs.id", "evaluation_runs.organization_id"],
            name="fk_agent_team_runs_evaluation_run_organization",
            ondelete="CASCADE",
        ),
        Index("ix_agent_team_runs_organization_created", "organization_id", "created_at"),
        Index("ix_agent_team_runs_thread", "thread_id"),
        Index("ix_agent_team_runs_team_id", "team_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    team_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    status: Mapped[RunStatus] = mapped_column(
        string_enum(RunStatus, "agent_team_run_status"),
        default=RunStatus.QUEUED,
        server_default=RunStatus.QUEUED.value,
    )
    objective: Mapped[str] = mapped_column(Text)
    final_output: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    state_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    step_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # M8: optional thread, and a count-only record of the memory injected (never the text).
    thread_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    memory_context: Mapped[dict[str, Any] | None] = mapped_column(JSONDocument)
    # M10: set when the run was executed by an evaluation (kept out of default run lists).
    evaluation_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class AgentTool(Timestamps, Base):
    """A tool an agent may call when acting as a team member.

    MCP assignments also reference the discovered tool row; the composite key makes it
    impossible to grant an agent another organization's MCP tool.
    """

    __tablename__ = "agent_tools"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_agent_tools_agent_organization",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["mcp_tool_id", "organization_id"],
            ["mcp_tools.id", "mcp_tools.organization_id"],
            name="fk_agent_tools_mcp_tool_organization",
            ondelete="CASCADE",
        ),
        UniqueConstraint("agent_id", "tool_key", name="uq_agent_tools_agent_key"),
        CheckConstraint(
            "(tool_key LIKE 'mcp:%') = (mcp_tool_id IS NOT NULL)",
            name="ck_agent_tools_mcp_reference",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tool_key: Mapped[str] = mapped_column(String(300))
    mcp_tool_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
