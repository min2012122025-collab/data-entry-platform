"""add structured rules, table mappings and direct login

Revision ID: 20260811_0003
Revises: 20260811_0002
Create Date: 2026-08-11
"""

import json

import sqlalchemy as sa
from alembic import op


revision = "20260811_0003"
down_revision = "20260811_0002"
branch_labels = None
depends_on = None


def _legacy_rules(required_fields, numeric_fields, date_fields):
    rules = []
    for field in json.loads(required_fields or "[]"):
        rules.append({
            "field": field,
            "rule_type": "required",
            "parameters": {},
            "severity": "warning",
            "message": f"{field}不能为空",
            "suggestion": f"请补充{field}后重新上传。",
            "enabled": True,
        })
    for field in json.loads(numeric_fields or "[]"):
        rules.append({
            "field": field,
            "rule_type": "data_type",
            "parameters": {"type": "number"},
            "severity": "warning",
            "message": f"{field}必须是数字",
            "suggestion": f"请将{field}修改为标准数字格式。",
            "enabled": True,
        })
    for field in json.loads(date_fields or "[]"):
        rules.append({
            "field": field,
            "rule_type": "date",
            "parameters": {},
            "severity": "warning",
            "message": f"{field}必须是有效日期",
            "suggestion": f"请将{field}修改为有效日期格式。",
            "enabled": True,
        })
    return rules


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "must_change_password",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        )
    op.execute(sa.text("UPDATE users SET must_change_password = 0"))

    if "validation_rules_json" not in {item["name"] for item in inspector.get_columns("template_versions")}:
        with op.batch_alter_table("template_versions") as batch:
            batch.add_column(sa.Column("validation_rules_json", sa.Text(), nullable=True))

    connection = bind
    rows = connection.execute(
        sa.text(
            "SELECT id, required_fields_json, numeric_fields_json, date_fields_json "
            "FROM template_versions"
        )
    ).mappings()
    for row in rows:
        rules = _legacy_rules(row["required_fields_json"], row["numeric_fields_json"], row["date_fields_json"])
        connection.execute(
            sa.text("UPDATE template_versions SET validation_rules_json = :rules WHERE id = :id"),
            {"rules": json.dumps(rules, ensure_ascii=False), "id": row["id"]},
        )
    with op.batch_alter_table("template_versions") as batch:
        batch.alter_column("validation_rules_json", existing_type=sa.Text(), nullable=False)

    data_connection_columns = {item["name"] for item in sa.inspect(bind).get_columns("data_connections")}
    with op.batch_alter_table("data_connections") as batch:
        if "server_uuid" not in data_connection_columns:
            batch.add_column(sa.Column("server_uuid", sa.String(length=64), nullable=True))
        if "same_instance" not in data_connection_columns:
            batch.add_column(sa.Column("same_instance", sa.Boolean(), nullable=False, server_default=sa.false()))

    if "template_table_mappings" not in sa.inspect(bind).get_table_names():
        op.create_table(
        "template_table_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("template_version_id", sa.Integer(), nullable=False),
        sa.Column("data_connection_id", sa.Integer(), nullable=False),
        sa.Column("target_schema", sa.String(length=128), nullable=False),
        sa.Column("target_table", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("last_validation_json", sa.Text(), nullable=False),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True),
        sa.Column("last_written_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["template_version_id"], ["template_versions.id"]),
        sa.ForeignKeyConstraint(["data_connection_id"], ["data_connections.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.UniqueConstraint("template_version_id", name="uq_template_table_mapping_version"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        )

    import_columns = {item["name"] for item in sa.inspect(bind).get_columns("import_batches")}
    import_foreign_keys = sa.inspect(bind).get_foreign_keys("import_batches")
    import_foreign_key_columns = {tuple(item.get("constrained_columns") or []) for item in import_foreign_keys}
    with op.batch_alter_table("import_batches") as batch:
        if "table_mapping_id" not in import_columns:
            batch.add_column(sa.Column("table_mapping_id", sa.Integer(), nullable=True))
        if "target_write_count" not in import_columns:
            batch.add_column(sa.Column("target_write_count", sa.Integer(), nullable=False, server_default="0"))
        if "voided_by_user_id" not in import_columns:
            batch.add_column(sa.Column("voided_by_user_id", sa.Integer(), nullable=True))
        if ("table_mapping_id",) not in import_foreign_key_columns:
            batch.create_foreign_key(
                "fk_import_batches_table_mapping",
                "template_table_mappings",
                ["table_mapping_id"],
                ["id"],
            )
        if ("voided_by_user_id",) not in import_foreign_key_columns:
            batch.create_foreign_key("fk_import_batches_voided_by", "users", ["voided_by_user_id"], ["id"])

    if "target_write_rows" not in sa.inspect(bind).get_table_names():
        op.create_table(
        "target_write_rows",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("import_batch_id", sa.Integer(), nullable=False),
        sa.Column("table_mapping_id", sa.Integer(), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("primary_key_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["import_batch_id"], ["import_batches.id"]),
        sa.ForeignKeyConstraint(["table_mapping_id"], ["template_table_mappings.id"]),
        sa.UniqueConstraint("import_batch_id", "row_index", name="uq_target_write_batch_row"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "target_write_rows" in inspector.get_table_names():
        op.drop_table("target_write_rows")
    import_columns = {item["name"] for item in sa.inspect(bind).get_columns("import_batches")}
    import_foreign_keys = sa.inspect(bind).get_foreign_keys("import_batches")
    with op.batch_alter_table("import_batches") as batch:
        for foreign_key in import_foreign_keys:
            columns = set(foreign_key.get("constrained_columns") or [])
            if columns & {"voided_by_user_id", "table_mapping_id"} and foreign_key.get("name"):
                batch.drop_constraint(foreign_key["name"], type_="foreignkey")
        if "voided_by_user_id" in import_columns:
            batch.drop_column("voided_by_user_id")
        if "target_write_count" in import_columns:
            batch.drop_column("target_write_count")
        if "table_mapping_id" in import_columns:
            batch.drop_column("table_mapping_id")
    if "template_table_mappings" in sa.inspect(bind).get_table_names():
        op.drop_table("template_table_mappings")
    with op.batch_alter_table("data_connections") as batch:
        batch.drop_column("same_instance")
        batch.drop_column("server_uuid")
    with op.batch_alter_table("template_versions") as batch:
        batch.drop_column("validation_rules_json")
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "must_change_password",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        )
