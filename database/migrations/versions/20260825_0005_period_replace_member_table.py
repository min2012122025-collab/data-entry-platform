"""add field mapping metadata for external business tables

Revision ID: 20260825_0005
Revises: 20260811_0004
Create Date: 2026-08-25

Business fact tables are provisioned outside the application schema. This
revision only extends the application-owned mapping metadata.
"""

import sqlalchemy as sa
from alembic import op


revision = "20260825_0005"
down_revision = "20260811_0004"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    mapping_columns = {item["name"] for item in sa.inspect(bind).get_columns("template_table_mappings")}
    if "field_mapping_json" not in mapping_columns:
        with op.batch_alter_table("template_table_mappings") as batch:
            batch.add_column(sa.Column("field_mapping_json", sa.Text(), nullable=True))
        op.execute(sa.text("UPDATE template_table_mappings SET field_mapping_json = '{}' WHERE field_mapping_json IS NULL"))
        with op.batch_alter_table("template_table_mappings") as batch:
            batch.alter_column("field_mapping_json", existing_type=sa.Text(), nullable=False)


def downgrade():
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("template_table_mappings")}
    if "field_mapping_json" in columns:
        with op.batch_alter_table("template_table_mappings") as batch:
            batch.drop_column("field_mapping_json")
