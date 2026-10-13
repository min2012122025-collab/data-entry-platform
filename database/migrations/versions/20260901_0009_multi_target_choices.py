"""Allow multiple saved targets per template sheet with one active choice.

Revision ID: 20260901_0009
Revises: 20260830_0008
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901_0009"
down_revision = "20260830_0008"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {item["name"] for item in inspector.get_columns("template_table_mappings")}
    if "is_active" not in columns:
        op.add_column(
            "template_table_mappings",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )

    constraints = {item["name"] for item in sa.inspect(op.get_bind()).get_unique_constraints("template_table_mappings")}
    with op.batch_alter_table("template_table_mappings") as batch:
        if "uq_template_table_mapping_version_sheet" in constraints:
            batch.drop_constraint("uq_template_table_mapping_version_sheet", type_="unique")
        if "uq_template_table_mapping_target" not in constraints:
            batch.create_unique_constraint(
                "uq_template_table_mapping_target",
                ["template_version_id", "source_sheet_name", "data_connection_id", "target_schema", "target_table"],
            )


def downgrade():
    duplicate = op.get_bind().execute(sa.text(
        "SELECT template_version_id, source_sheet_name FROM template_table_mappings "
        "GROUP BY template_version_id, source_sheet_name HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("多目标映射不能安全降级；生产环境禁止 downgrade")
    constraints = {item["name"] for item in sa.inspect(op.get_bind()).get_unique_constraints("template_table_mappings")}
    with op.batch_alter_table("template_table_mappings") as batch:
        if "uq_template_table_mapping_target" in constraints:
            batch.drop_constraint("uq_template_table_mapping_target", type_="unique")
        batch.create_unique_constraint(
            "uq_template_table_mapping_version_sheet", ["template_version_id", "source_sheet_name"]
        )
        batch.drop_column("is_active")
