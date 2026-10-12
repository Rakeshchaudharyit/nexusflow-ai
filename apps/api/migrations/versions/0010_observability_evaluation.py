"""observability and evaluation: run traces, spans, evaluation datasets/cases/runs/results"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_observability_evaluation"
down_revision = "0009_knowledge_rag"
branch_labels = None
depends_on = None

json_document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
JOB_TYPES_0009 = ("single_agent_run", "team_run", "approval_action", "knowledge_ingestion")
RESOURCE_0009 = (
    "(job_type = 'single_agent_run' AND agent_run_id IS NOT NULL AND team_run_id IS NULL"
    " AND approval_request_id IS NULL AND knowledge_document_id IS NULL)"
    " OR (job_type = 'team_run' AND team_run_id IS NOT NULL AND agent_run_id IS NULL"
    " AND approval_request_id IS NULL AND knowledge_document_id IS NULL)"
    " OR (job_type = 'approval_action' AND team_run_id IS NOT NULL"
    " AND approval_request_id IS NOT NULL AND agent_run_id IS NULL"
    " AND knowledge_document_id IS NULL)"
    " OR (job_type = 'knowledge_ingestion' AND knowledge_document_id IS NOT NULL"
    " AND agent_run_id IS NULL AND team_run_id IS NULL AND approval_request_id IS NULL)"
)
RESOURCE_0010 = (
    "(job_type = 'single_agent_run' AND agent_run_id IS NOT NULL AND team_run_id IS NULL"
    " AND approval_request_id IS NULL AND knowledge_document_id IS NULL"
    " AND evaluation_run_id IS NULL)"
    " OR (job_type = 'team_run' AND team_run_id IS NOT NULL AND agent_run_id IS NULL"
    " AND approval_request_id IS NULL AND knowledge_document_id IS NULL"
    " AND evaluation_run_id IS NULL)"
    " OR (job_type = 'approval_action' AND team_run_id IS NOT NULL"
    " AND approval_request_id IS NOT NULL AND agent_run_id IS NULL"
    " AND knowledge_document_id IS NULL AND evaluation_run_id IS NULL)"
    " OR (job_type = 'knowledge_ingestion' AND knowledge_document_id IS NOT NULL"
    " AND agent_run_id IS NULL AND team_run_id IS NULL AND approval_request_id IS NULL"
    " AND evaluation_run_id IS NULL)"
    " OR (job_type = 'evaluation_run' AND evaluation_run_id IS NOT NULL"
    " AND agent_run_id IS NULL AND team_run_id IS NULL AND approval_request_id IS NULL"
    " AND knowledge_document_id IS NULL)"
)
SPAN_TYPES = (
    "worker",
    "graph_node",
    "agent",
    "tool",
    "mcp",
    "knowledge_search",
    "memory_retrieval",
    "policy",
    "approval",
    "action",
    "retry",
)


def string_enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True)


def allowed(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


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


def org_fk(columns, table, name, ondelete="CASCADE"):
    return sa.ForeignKeyConstraint(
        [columns, "organization_id"],
        [f"{table}.id", f"{table}.organization_id"],
        name=name,
        ondelete=ondelete,
    )


def base_columns() -> list:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
    ]


def set_job_types(values: tuple[str, ...], resource_check: str) -> None:
    op.drop_constraint("execution_job_type", "execution_jobs", type_="check")
    op.drop_constraint("ck_execution_jobs_resource", "execution_jobs", type_="check")
    op.create_check_constraint("execution_job_type", "execution_jobs", allowed("job_type", values))
    op.create_check_constraint("ck_execution_jobs_resource", "execution_jobs", resource_check)


def upgrade():
    # --- evaluation --------------------------------------------------------------------------
    op.create_table(
        "evaluation_datasets",
        *base_columns(),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), server_default="", nullable=False),
        sa.Column(
            "dataset_type",
            string_enum("evaluation_dataset_type", "agent", "team", "rag", "policy", "mixed"),
            nullable=False,
        ),
        sa.Column(
            "status",
            string_enum("evaluation_dataset_status", "active", "archived"),
            server_default="active",
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_evaluation_datasets_id_organization"),
        sa.UniqueConstraint("organization_id", "name", name="uq_evaluation_datasets_org_name"),
    )
    op.create_table(
        "evaluation_cases",
        *base_columns(),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("target_kind", string_enum("evaluation_target", "agent", "team"), nullable=False),
        sa.Column("target_agent_id", sa.Uuid(), nullable=True),
        sa.Column("target_team_id", sa.Uuid(), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=False),
        sa.Column("setup_inputs", json_document, nullable=False),
        sa.Column("setup_memory", json_document, nullable=False),
        sa.Column("expected_status", sa.String(length=20), nullable=True),
        sa.Column("expected_intent", sa.String(length=40), nullable=True),
        sa.Column("expected_tool_key", sa.String(length=300), nullable=True),
        sa.Column("expected_output_contains", json_document, nullable=False),
        sa.Column("expected_output_excludes", json_document, nullable=False),
        sa.Column("expected_values", json_document, nullable=False),
        sa.Column("expected_citation_documents", json_document, nullable=False),
        sa.Column("expected_no_match", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("expected_policy_decision", sa.String(length=20), nullable=True),
        sa.Column("expected_action_type", sa.String(length=80), nullable=True),
        sa.Column("retrieval_k", sa.Integer(), server_default="5", nullable=False),
        sa.Column("metadata_json", json_document, nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        org_fk("dataset_id", "evaluation_datasets", "fk_evaluation_cases_dataset_organization"),
        org_fk("target_agent_id", "agents", "fk_evaluation_cases_agent_organization"),
        org_fk("target_team_id", "agent_teams", "fk_evaluation_cases_team_organization"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_evaluation_cases_id_organization"),
    )
    op.create_index(
        "ix_evaluation_cases_dataset_position", "evaluation_cases", ["dataset_id", "position"]
    )
    op.create_table(
        "evaluation_runs",
        *base_columns(),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            string_enum(
                "evaluation_run_status", "queued", "running", "completed", "failed", "cancelled"
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=10), nullable=False),
        sa.Column("target_agent_id", sa.Uuid(), nullable=True),
        sa.Column("target_team_id", sa.Uuid(), nullable=True),
        sa.Column("target_snapshot", json_document, nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=True),
        sa.Column("is_baseline", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("case_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("passed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "passed_count >= 0 AND failed_count >= 0", name="ck_evaluation_runs_counts"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        org_fk("dataset_id", "evaluation_datasets", "fk_evaluation_runs_dataset_organization"),
        org_fk("target_agent_id", "agents", "fk_evaluation_runs_agent_organization"),
        org_fk("target_team_id", "agent_teams", "fk_evaluation_runs_team_organization"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_evaluation_runs_id_organization"),
    )
    op.create_index(
        "ix_evaluation_runs_org_dataset_status",
        "evaluation_runs",
        ["organization_id", "dataset_id", "status"],
    )
    op.create_table(
        "evaluation_results",
        *base_columns(),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("actual_run_type", sa.String(length=10), nullable=True),
        sa.Column("actual_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", string_enum("evaluation_result", "passed", "failed", "error"), nullable=False
        ),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("checks_json", json_document, nullable=False),
        sa.Column("failure_reasons", json_document, nullable=False),
        sa.Column("actual_json", json_document, nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        org_fk("evaluation_run_id", "evaluation_runs", "fk_evaluation_results_run_organization"),
        org_fk("case_id", "evaluation_cases", "fk_evaluation_results_case_organization"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("evaluation_run_id", "case_id", name="uq_evaluation_results_run_case"),
    )
    # --- evaluation linkage on existing tables ---------------------------------------------
    for table in ("agent_runs", "agent_team_runs", "memory_threads", "execution_jobs"):
        op.add_column(table, sa.Column("evaluation_run_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_evaluation_run_organization",
            table,
            "evaluation_runs",
            ["evaluation_run_id", "organization_id"],
            ["id", "organization_id"],
            ondelete="CASCADE",
        )
    op.create_unique_constraint(
        "uq_execution_jobs_evaluation_run", "execution_jobs", ["evaluation_run_id"]
    )
    set_job_types((*JOB_TYPES_0009, "evaluation_run"), RESOURCE_0010)
    # --- observability -----------------------------------------------------------------------
    op.create_table(
        "run_traces",
        *base_columns(),
        sa.Column("run_type", string_enum("trace_run_type", "agent", "team"), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("team_run_id", sa.Uuid(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("evaluation_run_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("queue_wait_ms", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("span_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_category", sa.String(length=20), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "(run_type = 'agent' AND agent_run_id IS NOT NULL AND team_run_id IS NULL)"
            " OR (run_type = 'team' AND team_run_id IS NOT NULL AND agent_run_id IS NULL)",
            name="ck_run_traces_run",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_run_traces_attempts"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        org_fk("agent_run_id", "agent_runs", "fk_run_traces_agent_run_organization"),
        org_fk("team_run_id", "agent_team_runs", "fk_run_traces_team_run_organization"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_run_traces_id_organization"),
        sa.UniqueConstraint("agent_run_id", name="uq_run_traces_agent_run"),
        sa.UniqueConstraint("team_run_id", name="uq_run_traces_team_run"),
    )
    op.create_index(
        "ix_run_traces_organization_created", "run_traces", ["organization_id", "created_at"]
    )
    op.create_table(
        "trace_spans",
        *base_columns(),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("parent_span_id", sa.Uuid(), nullable=True),
        sa.Column("span_type", string_enum("trace_span_type", *SPAN_TYPES), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            string_enum("trace_span_status", "completed", "failed", "cancelled", "pending", "lost"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("tool_key", sa.String(length=300), nullable=True),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=True),
        sa.Column("knowledge_source_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("input_summary", sa.String(length=500), nullable=True),
        sa.Column("output_summary", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", json_document, nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_category", sa.String(length=20), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_trace_spans_duration"
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        org_fk("trace_id", "run_traces", "fk_trace_spans_trace_organization"),
        sa.ForeignKeyConstraint(
            ["parent_span_id"], ["trace_spans.id"], name="fk_trace_spans_parent", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trace_id", "sequence", name="uq_trace_spans_trace_sequence"),
    )
    op.create_index(
        "ix_trace_spans_org_type_started",
        "trace_spans",
        ["organization_id", "span_type", "started_at"],
    )


def downgrade():
    # Traces and evaluations have no pre-M10 representation. Evaluation-created runs, threads
    # and jobs are evaluation artifacts and are removed with them; all other M1-M9 rows stay.
    op.drop_index("ix_trace_spans_org_type_started", table_name="trace_spans")
    op.drop_table("trace_spans")
    op.drop_index("ix_run_traces_organization_created", table_name="run_traces")
    op.drop_table("run_traces")
    op.execute("DELETE FROM execution_jobs WHERE job_type = 'evaluation_run'")
    for table in ("agent_runs", "agent_team_runs", "memory_threads"):
        op.execute(f"DELETE FROM {table} WHERE evaluation_run_id IS NOT NULL")
    set_job_types(JOB_TYPES_0009, RESOURCE_0009)
    op.drop_constraint("uq_execution_jobs_evaluation_run", "execution_jobs", type_="unique")
    for table in ("execution_jobs", "memory_threads", "agent_team_runs", "agent_runs"):
        op.drop_constraint(f"fk_{table}_evaluation_run_organization", table, type_="foreignkey")
        op.drop_column(table, "evaluation_run_id")
    op.drop_table("evaluation_results")
    op.drop_index("ix_evaluation_runs_org_dataset_status", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    op.drop_index("ix_evaluation_cases_dataset_position", table_name="evaluation_cases")
    op.drop_table("evaluation_cases")
    op.drop_table("evaluation_datasets")
