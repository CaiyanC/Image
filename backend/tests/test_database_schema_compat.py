from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from app.core import database
from app.models import AIModelUsageLog, ToolRun


def test_product_qa_integrity_compat_adds_missing_legacy_columns(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE product_qa (
                id VARCHAR(36) PRIMARY KEY,
                product_id VARCHAR(36) NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL
            )
        """))

    monkeypatch.setattr(database, "engine", engine)
    database._ensure_product_qa_integrity_compat()

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("product_qa")}
    indexes = {index["name"] for index in inspector.get_indexes("product_qa")}

    assert {"integrity_status", "integrity_reason", "integrity_model", "integrity_audited_at"} <= columns
    assert "idx_product_qa_integrity" in indexes


def test_new_user_foreign_keys_match_the_postgresql_uuid_user_id_type():
    tool_runs_ddl = str(CreateTable(ToolRun.__table__).compile(dialect=postgresql.dialect())).lower()
    usage_logs_ddl = str(CreateTable(AIModelUsageLog.__table__).compile(dialect=postgresql.dialect())).lower()

    assert "created_by uuid" in tool_runs_ddl
    assert "user_id uuid" in usage_logs_ddl


def test_new_user_foreign_keys_remain_string_compatible_in_sqlite_tests():
    tool_runs_ddl = str(CreateTable(ToolRun.__table__).compile(dialect=sqlite.dialect())).lower()
    usage_logs_ddl = str(CreateTable(AIModelUsageLog.__table__).compile(dialect=sqlite.dialect())).lower()

    assert "created_by varchar(36)" in tool_runs_ddl
    assert "user_id varchar(36)" in usage_logs_ddl
