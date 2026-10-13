"""Support one target-table mapping per confirmed workbook sheet.

Revision ID: 20260830_0008
Revises: 20260830_0007
"""

import json

from alembic import op
import sqlalchemy as sa


revision = "20260830_0008"
down_revision = "20260830_0007"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    mapping_columns = {item["name"] for item in inspector.get_columns("template_table_mappings")}
    if "source_sheet_name" not in mapping_columns:
        with op.batch_alter_table("template_table_mappings") as batch:
            batch.add_column(sa.Column("source_sheet_name", sa.String(length=255), nullable=True))

    constraints = {item["name"] for item in sa.inspect(bind).get_unique_constraints("template_table_mappings")}
    with op.batch_alter_table("template_table_mappings") as batch:
        if "uq_template_table_mapping_version" in constraints:
            batch.drop_constraint("uq_template_table_mapping_version", type_="unique")
        if "uq_template_table_mapping_version_sheet" not in constraints:
            batch.create_unique_constraint(
                "uq_template_table_mapping_version_sheet", ["template_version_id", "source_sheet_name"]
            )

    batch_columns = {item["name"] for item in sa.inspect(bind).get_columns("import_batches")}
    if "target_mappings_json" not in batch_columns:
        op.add_column("import_batches", sa.Column("target_mappings_json", sa.Text(), nullable=True))
    operation_columns = {item["name"] for item in sa.inspect(bind).get_columns("target_write_operations")}
    if "mapping_snapshot_json" not in operation_columns:
        op.add_column("target_write_operations", sa.Column("mapping_snapshot_json", sa.Text(), nullable=True))

    rows = bind.execute(sa.text(
        "SELECT m.id, d.code, v.template_file_analysis_json "
        "FROM template_table_mappings m "
        "JOIN template_versions v ON v.id = m.template_version_id "
        "JOIN template_definitions d ON d.id = v.template_id "
        "WHERE m.source_sheet_name IS NULL"
    )).mappings().all()
    for row in rows:
        try:
            sheets = json.loads(row["template_file_analysis_json"] or "{}").get("sheets") or []
        except (TypeError, ValueError):
            sheets = []
        if len(sheets) == 1 and sheets[0].get("name"):
            bind.execute(
                sa.text("UPDATE template_table_mappings SET source_sheet_name=:sheet WHERE id=:id"),
                {"sheet": sheets[0]["name"], "id": row["id"]},
            )
        elif len(sheets) > 1 or row["code"] == "ap_performance_aging_v1":
            bind.execute(sa.text(
                "UPDATE template_table_mappings SET status='invalid', last_validation_json=:validation WHERE id=:id"
            ), {"id": row["id"], "validation": json.dumps({"valid": False, "errors": ["多工作表模板需要按工作表重新配置目标表"]}, ensure_ascii=False)})


def downgrade():
    bind = op.get_bind()
    duplicate = bind.execute(sa.text(
        "SELECT template_version_id FROM template_table_mappings GROUP BY template_version_id HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("多工作表映射不能安全降级；生产环境禁止 downgrade")
    constraints = {item["name"] for item in sa.inspect(bind).get_unique_constraints("template_table_mappings")}
    with op.batch_alter_table("template_table_mappings") as batch:
        if "uq_template_table_mapping_version_sheet" in constraints:
            batch.drop_constraint("uq_template_table_mapping_version_sheet", type_="unique")
        batch.create_unique_constraint("uq_template_table_mapping_version", ["template_version_id"])
        batch.drop_column("source_sheet_name")
    if "mapping_snapshot_json" in {item["name"] for item in sa.inspect(bind).get_columns("target_write_operations")}:
        op.drop_column("target_write_operations", "mapping_snapshot_json")
    if "target_mappings_json" in {item["name"] for item in sa.inspect(bind).get_columns("import_batches")}:
        op.drop_column("import_batches", "target_mappings_json")
