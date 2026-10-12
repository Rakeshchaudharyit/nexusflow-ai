"""multi-agent orchestration: teams, members, team runs, agent tool permissions"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_multi_agent_orchestration"
down_revision = "0004_mcp_registry"
branch_labels = None
depends_on = None

json_document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
SINGLE_RUN_EVENTS = (
    "run_started",
    "node_started",
    "node_completed",
    "node_failed",
    "run_completed",
    "run_failed",
)
TEAM_RUN_EVENTS = (
    "team_run_started",
    "supervisor_plan_created",
    "handoff_started",
    "agent_completed",
    "agent_failed",
    "validation_failed",
    "revision_requested",
    "team_run_completed",
    "team_run_failed",
)


def timestamps():
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def string_enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def event_type_check(values: tuple[str, ...]) -> str:
    return "event_type IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade():
    op.create_table(
        "agent_teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("description", sa.String(length=500), server_default="", nullable=False),
        sa.Column(
            "status",
            string_enum("agent_team_status", "draft", "active", "archived"),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_agent_teams_id_organization"),
        sa.UniqueConstraint("organization_id", "slug", name="uq_agent_teams_organization_slug"),
    )
    op.create_table(
        "agent_team_members",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            string_enum(
                "agent_team_role",
                "supervisor",
                "researcher",
                "customer_specialist",
                "analyst",
                "writer",
                "validator",
            ),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_required", sa.Boolean(), server_default="true", nullable=False),
        *timestamps(),
        sa.CheckConstraint("position >= 0", name="ck_agent_team_members_position"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_agent_team_members_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["agent_teams.id", "agent_teams.organization_id"],
            name="fk_agent_team_members_team_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "agent_id", name="uq_agent_team_members_team_agent"),
        sa.UniqueConstraint("team_id", "role", name="uq_agent_team_members_team_role"),
    )
    op.create_index(
        "ix_agent_team_members_agent_id", "agent_team_members", ["agent_id"], unique=False
    )
    op.create_table(
        "agent_team_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            string_enum(
                "agent_team_run_status", "queued", "running", "completed", "failed", "cancelled"
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("final_output", json_document, nullable=True),
        sa.Column("state_snapshot", json_document, nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("step_count", sa.Integer(), server_default="0", nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_agent_team_runs_duration"
        ),
        sa.CheckConstraint("step_count >= 0", name="ck_agent_team_runs_step_count"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["agent_teams.id", "agent_teams.organization_id"],
            name="fk_agent_team_runs_team_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_agent_team_runs_id_organization"),
    )
    op.create_index(
        "ix_agent_team_runs_organization_created",
        "agent_team_runs",
        ["organization_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_agent_team_runs_team_id", "agent_team_runs", ["team_id"], unique=False)

    op.create_unique_constraint(
        "uq_mcp_tools_id_organization", "mcp_tools", ["id", "organization_id"]
    )
    op.create_table(
        "agent_tools",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("tool_key", sa.String(length=300), nullable=False),
        sa.Column("mcp_tool_id", sa.Uuid(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "(tool_key LIKE 'mcp:%') = (mcp_tool_id IS NOT NULL)",
            name="ck_agent_tools_mcp_reference",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_agent_tools_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mcp_tool_id", "organization_id"],
            ["mcp_tools.id", "mcp_tools.organization_id"],
            name="fk_agent_tools_mcp_tool_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "tool_key", name="uq_agent_tools_agent_key"),
    )

    # One immutable event stream for both run kinds.
    op.alter_column("agent_run_events", "run_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("agent_run_events", sa.Column("team_run_id", sa.Uuid(), nullable=True))
    op.add_column("agent_run_events", sa.Column("agent_id", sa.Uuid(), nullable=True))
    op.add_column("agent_run_events", sa.Column("agent_role", sa.String(length=40), nullable=True))
    op.create_foreign_key(
        "fk_agent_run_events_team_run_organization",
        "agent_run_events",
        "agent_team_runs",
        ["team_run_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_agent_run_events_agent_organization",
        "agent_run_events",
        "agents",
        ["agent_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_agent_run_events_single_parent",
        "agent_run_events",
        "(run_id IS NULL) <> (team_run_id IS NULL)",
    )
    op.create_unique_constraint(
        "uq_agent_run_events_team_run_sequence", "agent_run_events", ["team_run_id", "sequence"]
    )
    # Non-native enums are VARCHAR sized to the longest value plus a CHECK of allowed values.
    op.drop_constraint("agent_run_event_type", "agent_run_events", type_="check")
    op.alter_column(
        "agent_run_events",
        "event_type",
        existing_type=sa.String(length=14),
        type_=sa.String(length=23),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "agent_run_event_type",
        "agent_run_events",
        event_type_check(SINGLE_RUN_EVENTS + TEAM_RUN_EVENTS),
    )


def downgrade():
    # Team events cannot exist without a single-agent run in the previous schema.
    op.execute("DELETE FROM agent_run_events WHERE team_run_id IS NOT NULL")
    op.drop_constraint("agent_run_event_type", "agent_run_events", type_="check")
    op.alter_column(
        "agent_run_events",
        "event_type",
        existing_type=sa.String(length=23),
        type_=sa.String(length=14),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "agent_run_event_type", "agent_run_events", event_type_check(SINGLE_RUN_EVENTS)
    )
    op.drop_constraint("uq_agent_run_events_team_run_sequence", "agent_run_events", type_="unique")
    op.drop_constraint("ck_agent_run_events_single_parent", "agent_run_events", type_="check")
    op.drop_constraint(
        "fk_agent_run_events_agent_organization", "agent_run_events", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_agent_run_events_team_run_organization", "agent_run_events", type_="foreignkey"
    )
    op.drop_column("agent_run_events", "agent_role")
    op.drop_column("agent_run_events", "agent_id")
    op.drop_column("agent_run_events", "team_run_id")
    op.alter_column("agent_run_events", "run_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_table("agent_tools")
    op.drop_constraint("uq_mcp_tools_id_organization", "mcp_tools", type_="unique")
    op.drop_index("ix_agent_team_runs_team_id", table_name="agent_team_runs")
    op.drop_index("ix_agent_team_runs_organization_created", table_name="agent_team_runs")
    op.drop_table("agent_team_runs")
    op.drop_index("ix_agent_team_members_agent_id", table_name="agent_team_members")
    op.drop_table("agent_team_members")
    op.drop_table("agent_teams")
