"""initial 通用录入平台 schema

Revision ID: 20260811_0001
Revises:
Create Date: 2026-08-11
"""

import sqlalchemy as sa
from alembic import op

from app.db.database import metadata


revision = "20260811_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind())


def downgrade():
    metadata.drop_all(op.get_bind())
    if "generic_records" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("generic_records")
