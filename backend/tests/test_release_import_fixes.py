"""Regression coverage for the September 7 import fixes, without business DBs."""
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, insert
from sqlalchemy.dialects import mysql, sqlite

from app.db.database import Database, target_write_operations


def test_shared_target_verification_keeps_sheets_separate():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    target = Table(
        "target", metadata, Column("id", Integer, primary_key=True),
        Column("import_batch_id", Integer), Column("source_sheet_name", String),
        Column("source_row_number", Integer),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(target), [
            {"id": 1, "import_batch_id": 28, "source_sheet_name": "甲", "source_row_number": 8},
            {"id": 2, "import_batch_id": 28, "source_sheet_name": "乙", "source_row_number": 8},
            {"id": 3, "import_batch_id": 29, "source_sheet_name": "甲", "source_row_number": 8},
        ])
        assert Database._target_rows_by_source(
            connection, target, 28, list(target.primary_key.columns), source_sheet_name="乙"
        ) == {("乙", 8): {"id": 2}}
        assert Database._target_rows_by_source(
            connection, target, 28, list(target.primary_key.columns)
        ) == {("甲", 8): {"id": 1}, ("乙", 8): {"id": 2}}
    engine.dispose()


def test_source_manifest_uses_large_text_on_mysql_and_remains_sqlite_compatible():
    column_type = target_write_operations.c.expected_sources_json.type
    assert column_type.compile(dialect=mysql.dialect()) == "LONGTEXT"
    assert column_type.compile(dialect=sqlite.dialect()) == "TEXT"
