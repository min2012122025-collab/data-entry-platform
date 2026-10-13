"""add data connection settings

Revision ID: 20260811_0002
Revises: 20260811_0001
Create Date: 2026-08-11
"""

import sqlalchemy as sa
from alembic import op


revision = "20260811_0002"
down_revision = "20260811_0001"
branch_labels = None
depends_on = None


def upgrade():
    if "data_connections" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "data_connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("connection_type", sa.String(length=32), nullable=False, server_default="mysql"),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="3306"),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("password_secret", sa.Text(), nullable=False),
        sa.Column("database_name", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("last_test_status", sa.String(length=32), nullable=True),
        sa.Column("last_test_message", sa.Text(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )


def downgrade():
    op.drop_table("data_connections")
