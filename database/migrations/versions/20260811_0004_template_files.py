"""add versioned template files and remove generated validation rules

Revision ID: 20260811_0004
Revises: 20260811_0003
Create Date: 2026-08-11
"""

import sqlalchemy as sa
from alembic import op


revision = "20260811_0004"
down_revision = "20260811_0003"
branch_labels = None
depends_on = None


def upgrade():
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("template_versions")}
    with op.batch_alter_table("template_versions") as batch:
        if "template_file_original_name" not in columns:
            batch.add_column(sa.Column("template_file_original_name", sa.String(length=512), nullable=True))
        if "template_file_path" not in columns:
            batch.add_column(sa.Column("template_file_path", sa.Text(), nullable=True))
        if "template_file_sha256" not in columns:
            batch.add_column(sa.Column("template_file_sha256", sa.String(length=64), nullable=True))
        if "template_file_size_bytes" not in columns:
            batch.add_column(sa.Column("template_file_size_bytes", sa.Integer(), nullable=True))
        if "template_file_uploaded_at" not in columns:
            batch.add_column(sa.Column("template_file_uploaded_at", sa.DateTime(), nullable=True))
        if "template_file_analysis_json" not in columns:
            batch.add_column(sa.Column("template_file_analysis_json", sa.Text(), nullable=True))
    op.execute(sa.text("UPDATE template_versions SET template_file_analysis_json = '{}' WHERE template_file_analysis_json IS NULL"))
    with op.batch_alter_table("template_versions") as batch:
        batch.alter_column("template_file_analysis_json", existing_type=sa.Text(), nullable=False)
    op.execute(sa.text("UPDATE template_versions SET validation_rules_json = '[]'"))


def downgrade():
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("template_versions")}
    with op.batch_alter_table("template_versions") as batch:
        for name in (
            "template_file_analysis_json",
            "template_file_uploaded_at",
            "template_file_size_bytes",
            "template_file_sha256",
            "template_file_path",
            "template_file_original_name",
        ):
            if name in columns:
                batch.drop_column(name)
