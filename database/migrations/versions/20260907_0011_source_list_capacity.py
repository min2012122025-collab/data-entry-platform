"""Widen operation source manifests for multi-thousand-row imports."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT

revision = '20260907_0011'
down_revision = '20260901_0010'
branch_labels = None
depends_on = None

def upgrade():
    if op.get_bind().dialect.name in ('mysql', 'mariadb'):
        op.alter_column('target_write_operations', 'expected_sources_json',
                        existing_type=sa.Text(), type_=LONGTEXT(), existing_nullable=False)

def downgrade():
    if op.get_bind().dialect.name in ('mysql', 'mariadb'):
        size = op.get_bind().execute(sa.text('SELECT COALESCE(MAX(OCTET_LENGTH(expected_sources_json)),0) FROM target_write_operations')).scalar_one()
        if size > 65535:
            raise RuntimeError('Cannot shrink source manifests: existing values exceed TEXT capacity')
        op.alter_column('target_write_operations', 'expected_sources_json',
                        existing_type=LONGTEXT(), type_=sa.Text(), existing_nullable=False)
