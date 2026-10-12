"""knowledge / RAG: pgvector, knowledge sources, documents, chunks, agent grants, ingestion jobs"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import UserDefinedType

revision = "0009_knowledge_rag"
down_revision = "0008_agent_memory"
branch_labels = None
depends_on = None

json_document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
DIMENSION = 384
JOB_TYPES_0007 = ("single_agent_run", "team_run", "approval_action")
RESOURCE_0007 = (
    "(job_type = 'single_agent_run' AND agent_run_id IS NOT NULL"
    " AND team_run_id IS NULL AND approval_request_id IS NULL)"
    " OR (job_type = 'team_run' AND team_run_id IS NOT NULL"
    " AND agent_run_id IS NULL AND approval_request_id IS NULL)"
    " OR (job_type = 'approval_action' AND team_run_id IS NOT NULL"
    " AND approval_request_id IS NOT NULL AND agent_run_id IS NULL)"
)
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


class Vector(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return f"vector({DIMENSION})"


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


def set_job_types(values: tuple[str, ...], resource_check: str) -> None:
    op.drop_constraint("execution_job_type", "execution_jobs", type_="check")
    op.drop_constraint("ck_execution_jobs_resource", "execution_jobs", type_="check")
    op.alter_column(
        "execution_jobs",
        "job_type",
        type_=sa.String(length=max(len(value) for value in values)),
        existing_nullable=False,
    )
    op.create_check_constraint("execution_job_type", "execution_jobs", allowed("job_type", values))
    op.create_check_constraint("ck_execution_jobs_resource", "execution_jobs", resource_check)


def enable_pgvector() -> None:
    """pgvector must be installed on the server (the Compose image builds it in). The extension
    is per database; it is created once in public and made resolvable for this migration even
    when it runs under a narrower search_path (as the migration tests do)."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
    op.execute(
        "SELECT set_config('search_path', current_setting('search_path') || ', '"
        " || (SELECT quote_ident(n.nspname) FROM pg_extension e"
        " JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'), true)"
    )


def upgrade():
    enable_pgvector()
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=1000), server_default="", nullable=False),
        sa.Column(
            "source_type", string_enum("knowledge_source_type", "text", "file"), nullable=False
        ),
        sa.Column(
            "status",
            string_enum(
                "knowledge_source_status", "draft", "processing", "ready", "failed", "archived"
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_provider", sa.String(length=40), nullable=False),
        sa.Column("embedding_model", sa.String(length=80), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("chunking_strategy", json_document, nullable=False),
        sa.Column("metadata_json", json_document, nullable=False),
        sa.Column("document_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_ingested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_knowledge_sources_id_organization"),
        sa.UniqueConstraint(
            "organization_id", "name", name="uq_knowledge_sources_organization_name"
        ),
    )
    op.create_index(
        "ix_knowledge_sources_organization_status",
        "knowledge_sources",
        ["organization_id", "status"],
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("extension", sa.String(length=10), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            string_enum("knowledge_document_status", "processing", "ready", "failed", "cancelled"),
            server_default="processing",
            nullable=False,
        ),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("ingested_version", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("extraction", json_document, nullable=True),
        sa.Column("ingestion_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint("size_bytes >= 0", name="ck_knowledge_documents_size"),
        sa.CheckConstraint("version >= 1", name="ck_knowledge_documents_version"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["knowledge_sources.id", "knowledge_sources.organization_id"],
            name="fk_knowledge_documents_source_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_knowledge_documents_id_organization"),
        sa.UniqueConstraint("source_id", "name", name="uq_knowledge_documents_source_name"),
    )
    op.create_index(
        "ix_knowledge_documents_source_status", "knowledge_documents", ["source_id", "status"]
    )
    op.create_index(
        "ix_knowledge_documents_checksum", "knowledge_documents", ["source_id", "checksum"]
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("metadata_json", json_document, nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["knowledge_documents.id", "knowledge_documents.organization_id"],
            name="fk_knowledge_chunks_document_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["knowledge_sources.id", "knowledge_sources.organization_id"],
            name="fk_knowledge_chunks_source_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id", "chunk_index", name="uq_knowledge_chunks_document_index"
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_org_source", "knowledge_chunks", ["organization_id", "source_id"]
    )
    # HNSW (cosine): no training step, good recall on small and growing datasets.
    op.create_index(
        "ix_knowledge_chunks_embedding_hnsw",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_knowledge_chunks_content_fts",
        "knowledge_chunks",
        [sa.text("to_tsvector('english', content)")],
        postgresql_using="gin",
    )
    op.create_table(
        "agent_knowledge_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="true", nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agents.id", "agents.organization_id"],
            name="fk_agent_knowledge_sources_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["knowledge_sources.id", "knowledge_sources.organization_id"],
            name="fk_agent_knowledge_sources_source_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agent_id", "source_id", name="uq_agent_knowledge_sources_agent_source"
        ),
    )
    op.create_index(
        "ix_agent_knowledge_sources_org_agent",
        "agent_knowledge_sources",
        ["organization_id", "agent_id"],
    )
    op.add_column("execution_jobs", sa.Column("knowledge_document_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_execution_jobs_knowledge_document_organization",
        "execution_jobs",
        "knowledge_documents",
        ["knowledge_document_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_execution_jobs_knowledge_document", "execution_jobs", ["knowledge_document_id"]
    )
    set_job_types((*JOB_TYPES_0007, "knowledge_ingestion"), RESOURCE_0009)


def downgrade():
    # Knowledge has no pre-M9 representation: its jobs and tables go. M1-M8 rows are kept.
    # The vector extension stays installed: other schemas in the database may use it.
    op.execute("DELETE FROM execution_jobs WHERE job_type = 'knowledge_ingestion'")
    set_job_types(JOB_TYPES_0007, RESOURCE_0007)
    op.drop_index("ix_execution_jobs_knowledge_document", table_name="execution_jobs")
    op.drop_constraint(
        "fk_execution_jobs_knowledge_document_organization", "execution_jobs", type_="foreignkey"
    )
    op.drop_column("execution_jobs", "knowledge_document_id")
    op.drop_index("ix_agent_knowledge_sources_org_agent", table_name="agent_knowledge_sources")
    op.drop_table("agent_knowledge_sources")
    for name in (
        "ix_knowledge_chunks_content_fts",
        "ix_knowledge_chunks_embedding_hnsw",
        "ix_knowledge_chunks_org_source",
    ):
        op.drop_index(name, table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_documents_checksum", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_source_status", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("ix_knowledge_sources_organization_status", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
