"""add recoverable cross-instance target writes

Revision ID: 20260830_0007
Revises: 20260829_0006
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op


revision = "20260830_0007"
down_revision = "20260829_0006"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("import_batches")}
    additions = {
        "target_connection_id": sa.Column("target_connection_id", sa.Integer(), nullable=True),
        "target_schema": sa.Column("target_schema", sa.String(length=128), nullable=True),
        "target_table": sa.Column("target_table", sa.String(length=128), nullable=True),
        "target_field_mapping_json": sa.Column("target_field_mapping_json", sa.Text(), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("import_batches", column)

    if "target_write_operations" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "target_write_operations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("operation_key", sa.String(length=36), nullable=False),
            sa.Column("operation_type", sa.String(length=32), nullable=False),
            sa.Column("batch_id", sa.Integer(), sa.ForeignKey("import_batches.id"), nullable=False),
            sa.Column("previous_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id"), nullable=True),
            sa.Column("table_mapping_id", sa.Integer(), sa.ForeignKey("template_table_mappings.id"), nullable=False),
            sa.Column("data_connection_id", sa.Integer(), sa.ForeignKey("data_connections.id"), nullable=False),
            sa.Column("target_schema", sa.String(length=128), nullable=False),
            sa.Column("target_table", sa.String(length=128), nullable=False),
            sa.Column("expected_row_count", sa.Integer(), nullable=False),
            sa.Column("expected_sources_json", sa.Text(), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("active_scope_key", sa.String(length=160), nullable=True),
            sa.Column("target_committed_at", sa.DateTime(), nullable=True),
            sa.Column("finalized_at", sa.DateTime(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("operation_key", name="uq_target_write_operation_key"),
            sa.UniqueConstraint("active_scope_key", name="uq_target_write_active_scope"),
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "generic_records" in tables:
        batches = sa.table(
            "import_batches",
            sa.column("id", sa.Integer()),
            sa.column("status", sa.String()),
            sa.column("committed_at", sa.DateTime()),
            sa.column("table_mapping_id", sa.Integer()),
            sa.column("target_write_count", sa.Integer()),
            sa.column("active_commit_key", sa.String()),
        )
        affected = sa.select(batches.c.id).where(
            batches.c.committed_at.is_not(None),
            batches.c.table_mapping_id.is_(None),
            batches.c.target_write_count == 0,
        )
        discarded_count = bind.execute(
            sa.select(sa.func.count()).select_from(affected.subquery())
        ).scalar_one()
        tasks = sa.table(
            "monthly_tasks",
            sa.column("current_batch_id", sa.Integer()),
            sa.column("status", sa.String()),
            sa.column("updated_at", sa.DateTime()),
        )
        bind.execute(
            sa.update(tasks)
            .where(tasks.c.current_batch_id.in_(affected))
            .values(status="pending_submission", current_batch_id=None, updated_at=sa.func.now())
        )
        bind.execute(
            sa.update(batches)
            .where(
                batches.c.committed_at.is_not(None),
                batches.c.table_mapping_id.is_(None),
                batches.c.target_write_count == 0,
            )
            .values(status="discarded", active_commit_key=None)
        )
        if "audit_logs" in tables:
            audit = sa.table(
                "audit_logs",
                sa.column("actor_user_id", sa.Integer()),
                sa.column("action", sa.String()),
                sa.column("target_type", sa.String()),
                sa.column("target_id", sa.String()),
                sa.column("message", sa.Text()),
                sa.column("payload_json", sa.Text()),
            )
            bind.execute(
                sa.insert(audit).values(
                    actor_user_id=None,
                    action="migration.discard_internal_records",
                    target_type="database",
                    target_id="generic_records",
                    message="废弃未写入目标业务库的历史内部批次",
                    payload_json='{"discarded_batch_count": %d}' % discarded_count,
                )
            )
        op.drop_table("generic_records")


def downgrade():
    if "generic_records" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "generic_records",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("import_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id"), nullable=False),
            sa.Column("template_code", sa.String(length=128), nullable=False),
            sa.Column("report_month", sa.String(length=7), nullable=False),
            sa.Column("sheet_name", sa.String(length=255), nullable=False),
            sa.Column("row_number", sa.Integer(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    op.drop_table("target_write_operations")
    with op.batch_alter_table("import_batches") as batch:
        batch.drop_column("target_field_mapping_json")
        batch.drop_column("target_table")
        batch.drop_column("target_schema")
        batch.drop_column("target_connection_id")
