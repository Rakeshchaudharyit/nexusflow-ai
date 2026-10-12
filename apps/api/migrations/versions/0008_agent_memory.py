"""agent memory: threads, memory entries, run thread links, memory events"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_agent_memory"
down_revision = "0007_background_execution"
branch_labels = None
depends_on = None

json_document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
EVENTS_0007 = (
    "run_started",
    "node_started",
    "node_completed",
    "node_failed",
    "run_completed",
    "run_failed",
    "team_run_started",
    "supervisor_plan_created",
    "handoff_started",
    "agent_completed",
    "agent_failed",
    "validation_failed",
    "revision_requested",
    "team_run_completed",
    "team_run_failed",
    "action_proposed",
    "policy_allowed",
    "policy_denied",
    "approval_requested",
    "approval_approved",
    "approval_rejected",
    "approval_expired",
    "action_started",
    "action_completed",
    "action_failed",
    "retry_scheduled",
    "run_cancelled",
    "team_run_cancelled",
)
M8_EVENTS = ("memory_saved", "memory_updated")


def string_enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def allowed(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def set_event_types(values: tuple[str, ...]) -> None:
    # VARCHAR(23) since 0005; both M8 names fit, so only the CHECK changes.
    op.drop_constraint("agent_run_event_type", "agent_run_events", type_="check")
    op.create_check_constraint(
        "agent_run_event_type", "agent_run_events", allowed("event_type", values)
    )


def timestamps() -> list[sa.Column]:
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


def upgrade():
    op.create_table(
        "memory_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            string_enum("memory_thread_status", "active", "archived"),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *timestamps(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_memory_threads_id_organization"),
    )
    op.create_index(
        "ix_memory_threads_organization_activity",
        "memory_threads",
        ["organization_id", "last_activity_at"],
    )
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "memory_type",
            string_enum(
                "memory_type",
                "thread_memory",
                "agent_memory",
                "workspace_memory",
                "fact_memory",
                "summary_memory",
            ),
            nullable=False,
        ),
        sa.Column(
            "scope", string_enum("memory_scope", "thread", "agent", "workspace"), nullable=False
        ),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("fact_key", sa.String(length=80), nullable=True),
        sa.Column("fact_value", sa.String(length=500), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=True),
        sa.Column("importance", sa.Integer(), server_default="3", nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "source_type",
            string_enum(
                "memory_source_type",
                "manual_user_entry",
                "user_input",
                "agent_run",
                "team_run",
                "approved_action",
                "thread_summary",
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "(scope = 'thread' AND thread_id IS NOT NULL)"
            " OR (scope = 'agent' AND agent_id IS NOT NULL AND thread_id IS NULL)"
            " OR (scope = 'workspace' AND thread_id IS NULL AND agent_id IS NULL)",
            name="ck_memory_entries_scope",
        ),
        sa.CheckConstraint(
            "(memory_type IN ('thread_memory', 'summary_memory') AND scope = 'thread')"
            " OR (memory_type = 'agent_memory' AND scope = 'agent')"
            " OR (memory_type = 'workspace_memory' AND scope = 'workspace')"
            " OR (memory_type = 'fact_memory' AND fact_key IS NOT NULL"
            " AND fact_value IS NOT NULL)",
            name="ck_memory_entries_type",
        ),
        sa.CheckConstraint("importance BETWEEN 1 AND 5", name="ck_memory_entries_importance"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_memory_entries_confidence",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["thread_id", "organization_id"],
            ["memory_threads.id", "memory_threads.organization_id"],
            name="fk_memory_entries_thread_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_memory_entries_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["agent_teams.id", "agent_teams.organization_id"],
            name="fk_memory_entries_team_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_memory_entries_idempotency"
        ),
    )
    for name, columns in (
        ("ix_memory_entries_org_thread", ["organization_id", "thread_id", "is_active"]),
        ("ix_memory_entries_org_agent", ["organization_id", "agent_id", "is_active"]),
        ("ix_memory_entries_org_type", ["organization_id", "memory_type", "is_active"]),
        ("ix_memory_entries_source", ["source_type", "source_id"]),
    ):
        op.create_index(name, "memory_entries", columns)
    for table, prefix in (("agent_runs", "agent_runs"), ("agent_team_runs", "agent_team_runs")):
        op.add_column(table, sa.Column("thread_id", sa.Uuid(), nullable=True))
        op.add_column(table, sa.Column("memory_context", json_document, nullable=True))
        op.create_foreign_key(
            f"fk_{prefix}_thread_organization",
            table,
            "memory_threads",
            ["thread_id", "organization_id"],
            ["id", "organization_id"],
        )
        op.create_index(f"ix_{prefix}_thread", table, ["thread_id"])
    for table in ("agents", "agent_teams"):
        op.add_column(
            table,
            sa.Column(
                "workspace_memory_enabled", sa.Boolean(), server_default="false", nullable=False
            ),
        )
    set_event_types(EVENTS_0007 + M8_EVENTS)


def downgrade():
    # Memory has no pre-M8 representation: its events go, runs lose their thread links, and
    # the memory tables are dropped. No M1-M7 rows are removed.
    op.execute("DELETE FROM agent_run_events WHERE " + allowed("event_type", M8_EVENTS))
    set_event_types(EVENTS_0007)
    for table in ("agent_teams", "agents"):
        op.drop_column(table, "workspace_memory_enabled")
    for table in ("agent_team_runs", "agent_runs"):
        op.drop_index(f"ix_{table}_thread", table_name=table)
        op.drop_constraint(f"fk_{table}_thread_organization", table, type_="foreignkey")
        op.drop_column(table, "memory_context")
        op.drop_column(table, "thread_id")
    for name in (
        "ix_memory_entries_source",
        "ix_memory_entries_org_type",
        "ix_memory_entries_org_agent",
        "ix_memory_entries_org_thread",
    ):
        op.drop_index(name, table_name="memory_entries")
    op.drop_table("memory_entries")
    op.drop_index("ix_memory_threads_organization_activity", table_name="memory_threads")
    op.drop_table("memory_threads")
