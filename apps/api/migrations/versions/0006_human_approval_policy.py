"""human approval and action policy: approval requests and action executions"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_human_approval_policy"
down_revision = "0005_multi_agent_orchestration"
branch_labels = None
depends_on = None

json_document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
RUN_STATUSES = ("queued", "running", "completed", "failed", "cancelled")
EXISTING_EVENTS = (
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
)
M6_EVENTS = (
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
)


def string_enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def allowed(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def set_run_statuses(values: tuple[str, ...], length: int, previous: int) -> None:
    # Non-native enums are VARCHAR(longest value) plus a CHECK; "awaiting_approval" needs 17.
    for table, constraint in (
        ("agent_runs", "agent_run_status"),
        ("agent_team_runs", "agent_team_run_status"),
    ):
        op.drop_constraint(constraint, table, type_="check")
        op.alter_column(
            table,
            "status",
            existing_type=sa.String(length=previous),
            type_=sa.String(length=length),
            existing_nullable=False,
            existing_server_default=sa.text("'queued'"),
        )
        op.create_check_constraint(constraint, table, allowed("status", values))


def set_event_types(values: tuple[str, ...]) -> None:
    # The column is already VARCHAR(23) from 0005; every M6 name fits, so only the CHECK changes.
    op.drop_constraint("agent_run_event_type", "agent_run_events", type_="check")
    op.create_check_constraint(
        "agent_run_event_type", "agent_run_events", allowed("event_type", values)
    )


def upgrade():
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("team_run_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("proposed_by_agent_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("payload", json_document, nullable=False),
        sa.Column(
            "risk_level",
            string_enum("approval_risk_level", "low", "medium", "high"),
            nullable=False,
        ),
        sa.Column("rule_key", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            string_enum("approval_status", "pending", "approved", "rejected", "expired"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("review_comment", sa.String(length=1000), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("expires_at > created_at", name="ck_approval_requests_expiry"),
        sa.ForeignKeyConstraint(
            ["proposed_by_agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_approval_requests_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["agent_teams.id", "agent_teams.organization_id"],
            name="fk_approval_requests_team_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_run_id", "organization_id"],
            ["agent_team_runs.id", "agent_team_runs.organization_id"],
            name="fk_approval_requests_team_run_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_approval_requests_id_organization"),
        sa.UniqueConstraint("team_run_id", name="uq_approval_requests_team_run"),
    )
    op.create_index(
        "ix_approval_requests_organization_status",
        "approval_requests",
        ["organization_id", "status", "created_at"],
        unique=False,
    )
    op.create_table(
        "action_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("team_run_id", sa.Uuid(), nullable=False),
        sa.Column("approval_request_id", sa.Uuid(), nullable=True),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("payload", json_document, nullable=False),
        sa.Column(
            "status",
            string_enum("action_execution_status", "completed", "failed"),
            nullable=False,
        ),
        sa.Column("result", json_document, nullable=False),
        sa.Column("executed_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approval_request_id", "organization_id"],
            ["approval_requests.id", "approval_requests.organization_id"],
            name="fk_action_executions_approval_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["executed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["team_run_id", "organization_id"],
            ["agent_team_runs.id", "agent_team_runs.organization_id"],
            name="fk_action_executions_team_run_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("approval_request_id", name="uq_action_executions_approval"),
        sa.UniqueConstraint("team_run_id", name="uq_action_executions_team_run"),
    )
    op.create_index(
        "ix_action_executions_organization_created",
        "action_executions",
        ["organization_id", "created_at"],
        unique=False,
    )
    set_run_statuses((*RUN_STATUSES, "awaiting_approval"), length=17, previous=9)
    set_event_types(EXISTING_EVENTS + M6_EVENTS)


def downgrade():
    # Paused runs cannot be represented before M6; record them as cancelled, and drop the
    # M6 events (their approvals and executions go with the tables).
    for table in ("agent_runs", "agent_team_runs"):
        op.execute(f"UPDATE {table} SET status = 'cancelled' WHERE status = 'awaiting_approval'")
    op.execute("DELETE FROM agent_run_events WHERE " + allowed("event_type", M6_EVENTS))
    set_event_types(EXISTING_EVENTS)
    set_run_statuses(RUN_STATUSES, length=9, previous=17)
    op.drop_index("ix_action_executions_organization_created", table_name="action_executions")
    op.drop_table("action_executions")
    op.drop_index("ix_approval_requests_organization_status", table_name="approval_requests")
    op.drop_table("approval_requests")
