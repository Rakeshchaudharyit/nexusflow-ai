import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects.postgresql import JSONB


def test_migrations_upgrade_downgrade_upgrade():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL is required to verify production migrations")
    engine = create_engine(url)
    schema = "test_migration_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            assert set(inspect(connection).get_table_names(schema=schema)) == {
                "alembic_version",
                "users",
                "organizations",
                "organization_memberships",
                "refresh_sessions",
                "agents",
                "agent_runs",
                "agent_run_events",
                "mcp_servers",
                "mcp_tools",
                "agent_teams",
                "agent_team_members",
                "agent_team_runs",
                "agent_tools",
                "approval_requests",
                "action_executions",
                "execution_jobs",
                "memory_threads",
                "memory_entries",
                "knowledge_sources",
                "knowledge_documents",
                "knowledge_chunks",
                "agent_knowledge_sources",
                "run_traces",
                "trace_spans",
                "evaluation_datasets",
                "evaluation_cases",
                "evaluation_runs",
                "evaluation_results",
            }
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0010_observability_evaluation"
            )
            columns = {
                column["name"]: column["type"]
                for column in inspect(connection).get_columns("agent_runs", schema=schema)
            }
            assert isinstance(columns["state_snapshot"], JSONB)
            tool_columns = {
                column["name"]: column["type"]
                for column in inspect(connection).get_columns("mcp_tools", schema=schema)
            }
            assert isinstance(tool_columns["input_schema"], JSONB)
            status = next(
                column
                for column in inspect(connection).get_columns("agent_team_runs", schema=schema)
                if column["name"] == "status"
            )
            assert status["type"].length == 17
            approval_status = next(
                column
                for column in inspect(connection).get_columns("approval_requests", schema=schema)
                if column["name"] == "status"
            )
            assert approval_status["type"].length == 9
            assert "attempt" in {
                column["name"]
                for column in inspect(connection).get_columns("agent_run_events", schema=schema)
            }
            embedding = next(
                column
                for column in inspect(connection).get_columns("knowledge_chunks", schema=schema)
                if column["name"] == "embedding"
            )
            assert embedding["type"].get_col_spec() == "vector(384)"
            job_type = next(
                column
                for column in inspect(connection).get_columns("execution_jobs", schema=schema)
                if column["name"] == "job_type"
            )
            assert job_type["type"].length == len("knowledge_ingestion")
            command.downgrade(config, "0009_knowledge_rag")
            tables = inspect(connection).get_table_names(schema=schema)
            assert "run_traces" not in tables and "evaluation_runs" not in tables
            assert "knowledge_chunks" in tables
            assert "evaluation_run_id" not in {
                column["name"]
                for column in inspect(connection).get_columns("agent_runs", schema=schema)
            }
            command.upgrade(config, "head")
            command.downgrade(config, "0008_agent_memory")
            tables = inspect(connection).get_table_names(schema=schema)
            assert "knowledge_chunks" not in tables and "memory_entries" in tables
            assert "knowledge_document_id" not in {
                column["name"]
                for column in inspect(connection).get_columns("execution_jobs", schema=schema)
            }
            command.upgrade(config, "head")
            command.downgrade(config, "0007_background_execution")
            assert "memory_entries" not in inspect(connection).get_table_names(schema=schema)
            assert "thread_id" not in {
                column["name"]
                for column in inspect(connection).get_columns("agent_runs", schema=schema)
            }
            command.upgrade(config, "head")
            command.downgrade(config, "0006_human_approval_policy")
            assert "execution_jobs" not in inspect(connection).get_table_names(schema=schema)
            assert "attempt" not in {
                column["name"]
                for column in inspect(connection).get_columns("agent_run_events", schema=schema)
            }
            command.upgrade(config, "head")
            command.downgrade(config, "0005_multi_agent_orchestration")
            assert "approval_requests" not in inspect(connection).get_table_names(schema=schema)
            command.upgrade(config, "head")
            command.downgrade(config, "0004_mcp_registry")
            tables = inspect(connection).get_table_names(schema=schema)
            assert "agent_teams" not in tables and "mcp_tools" in tables
            event_columns = {
                column["name"]: column
                for column in inspect(connection).get_columns("agent_run_events", schema=schema)
            }
            assert "team_run_id" not in event_columns
            assert event_columns["run_id"]["nullable"] is False
            command.upgrade(config, "head")
            command.downgrade(config, "0003_agent_runtime")
            assert "mcp_servers" not in inspect(connection).get_table_names(schema=schema)
            assert "agent_runs" in inspect(connection).get_table_names(schema=schema)
            command.downgrade(config, "0002_identity")
            assert "agents" not in inspect(connection).get_table_names(schema=schema)
            assert "users" in inspect(connection).get_table_names(schema=schema)
            command.downgrade(config, "0001_foundation")
            assert inspect(connection).get_table_names(schema=schema) == ["alembic_version"]
            command.upgrade(config, "head")
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "0010_observability_evaluation"
            )
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
