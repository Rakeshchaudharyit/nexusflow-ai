"""background execution: execution jobs, event attempts, cancellation statuses"""

import sqlalchemy as sa
from alembic import op

revision = "0007_background_execution"
down_revision = "0006_human_approval_policy"
branch_labels = None
depends_on = None

EVENTS_0006 = (
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
)
M7_EVENTS = ("retry_scheduled", "run_cancelled", "team_run_cancelled")
APPROVALS_0006 = ("pending", "approved", "rejected", "expired")


def string_enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def allowed(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def set_event_types(values: tuple[str, ...]) -> None:
    # VARCHAR(23) since 0005; every M7 name fits, so only the CHECK changes.
    op.drop_constraint("agent_run_event_type", "agent_run_events", type_="check")
    op.create_check_constraint(
        "agent_run_event_type", "agent_run_events", allowed("event_type", values)
    )


def set_approval_statuses(values: tuple[str, ...], length: int, previous: int) -> None:
    # Non-native enum: VARCHAR(longest value) plus a CHECK; "cancelled" needs 9.
    op.drop_constraint("approval_status", "approval_requests", type_="check")
    op.alter_column(
        "approval_requests",
        "status",
        existing_type=sa.String(length=previous),
        type_=sa.String(length=length),
        existing_nullable=False,
        existing_server_default=sa.text("'pending'"),
    )
    op.create_check_constraint("approval_status", "approval_requests", allowed("status", values))


def upgrade():
    op.create_table(
        "execution_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column(
            "job_type",
            string_enum("execution_job_type", "single_agent_run", "team_run", "approval_action"),
            nullable=False,
        ),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("team_run_id", sa.Uuid(), nullable=True),
        sa.Column("approval_request_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            string_enum(
                "execution_job_status",
                "queued",
                "running",
                "retrying",
                "completed",
                "failed",
                "cancelled",
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("queue_name", sa.String(length=80), nullable=False),
        sa.Column("worker_id", sa.String(length=160), nullable=True),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "(job_type = 'single_agent_run' AND agent_run_id IS NOT NULL"
            " AND team_run_id IS NULL AND approval_request_id IS NULL)"
            " OR (job_type = 'team_run' AND team_run_id IS NOT NULL"
            " AND agent_run_id IS NULL AND approval_request_id IS NULL)"
            " OR (job_type = 'approval_action' AND team_run_id IS NOT NULL"
            " AND approval_request_id IS NOT NULL AND agent_run_id IS NULL)",
            name="ck_execution_jobs_resource",
        ),
        sa.CheckConstraint(
            "attempt >= 0 AND attempt <= max_attempts", name="ck_execution_jobs_attempt"
        ),
        sa.CheckConstraint("max_attempts >= 1", name="ck_execution_jobs_max_attempts"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_run_id", "organization_id"],
            ["agent_runs.id", "agent_runs.organization_id"],
            name="fk_execution_jobs_agent_run_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_run_id", "organization_id"],
            ["agent_team_runs.id", "agent_team_runs.organization_id"],
            name="fk_execution_jobs_team_run_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approval_request_id", "organization_id"],
            ["approval_requests.id", "approval_requests.organization_id"],
            name="fk_execution_jobs_approval_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_run_id", name="uq_execution_jobs_agent_run"),
        sa.UniqueConstraint("job_type", "team_run_id", name="uq_execution_jobs_team_run_type"),
        sa.UniqueConstraint("approval_request_id", name="uq_execution_jobs_approval"),
    )
    op.create_index(
        "ix_execution_jobs_organization_created",
        "execution_jobs",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_execution_jobs_status_heartbeat", "execution_jobs", ["status", "heartbeat_at"]
    )
    op.create_index(
        "ix_execution_jobs_status_next_retry", "execution_jobs", ["status", "next_retry_at"]
    )
    op.add_column("agent_run_events", sa.Column("attempt", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_agent_run_events_attempt", "agent_run_events", "attempt IS NULL OR attempt > 0"
    )
    set_event_types(EVENTS_0006 + M7_EVENTS)
    set_approval_statuses((*APPROVALS_0006, "cancelled"), length=9, previous=8)


def downgrade():
    # Pre-M7 schemas cannot represent these rows: a cancelled approval was never executed, so it
    # becomes "expired"; M7-only events are removed; queued/running work loses its job record.
    op.execute("UPDATE approval_requests SET status = 'expired' WHERE status = 'cancelled'")
    # Pre-M7 code never picks up queued work, so close it instead of leaving it waiting forever.
    for table in ("agent_runs", "agent_team_runs"):
        op.execute(f"UPDATE {table} SET status = 'cancelled' WHERE status IN ('queued', 'running')")
    set_approval_statuses(APPROVALS_0006, length=8, previous=9)
    op.execute("DELETE FROM agent_run_events WHERE " + allowed("event_type", M7_EVENTS))
    set_event_types(EVENTS_0006)
    op.drop_constraint("ck_agent_run_events_attempt", "agent_run_events", type_="check")
    op.drop_column("agent_run_events", "attempt")
    op.drop_index("ix_execution_jobs_status_next_retry", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_status_heartbeat", table_name="execution_jobs")
    op.drop_index("ix_execution_jobs_organization_created", table_name="execution_jobs")
    op.drop_table("execution_jobs")
