"""Add safe archive markers for users, templates, and mappings.

Revision ID: 20260901_0010
Revises: 20260901_0009
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901_0010"
down_revision = "20260901_0009"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table_name in ("users", "template_definitions", "template_table_mappings"):
        columns = {item["name"] for item in inspector.get_columns(table_name)}
        if "archived_at" not in columns:
            op.add_column(table_name, sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade():
    for table_name in ("template_table_mappings", "template_definitions", "users"):
        columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}
        if "archived_at" in columns:
            with op.batch_alter_table(table_name) as batch:
                batch.drop_column("archived_at")
