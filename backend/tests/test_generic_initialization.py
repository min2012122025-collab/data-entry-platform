import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault('ENTRY_ENV', 'test')
os.environ.setdefault('ENTRY_ALLOW_SQLITE', '1')
os.environ.setdefault('ENTRY_DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('ENTRY_SECRET_KEY', 'test-generic-secret')

from app.db.database import Database, metadata


def test_new_install_has_only_admin_and_no_business_templates():
    database = Database('sqlite:///:memory:')
    metadata.create_all(database.engine)
    database.ensure_production_seed_data()
    database.ensure_production_seed_data()
    assert [user['username'] for user in database.list_users()] == ['admin']
    assert database.list_templates() == []
    assert database.list_task_months({'id': 1, 'role': 'admin'}) == []


def test_fresh_install_verifier_accepts_empty_generic_install():
    from database.operations.verify_fresh_install import verify
    database = Database('sqlite:///:memory:')
    metadata.create_all(database.engine)
    database.ensure_production_seed_data()
    assert verify(database, verify_schema=False) == {
        'admin': 'admin', 'templates': 0, 'tasks': 0, 'months': [], 'history_rows': 0,
    }


def test_development_initialization_creates_a_startable_database(tmp_path):
    root = Path(__file__).resolve().parents[2]
    url = f'sqlite:///{tmp_path / "demo.db"}'
    environment = dict(os.environ, ENTRY_ENV='development', ENTRY_DATABASE_URL=url,
                       ENTRY_ALLOW_SQLITE='1', ENTRY_SECRET_KEY='local-test-secret',
                       PYTHONPATH=str(root / 'backend'))
    result = subprocess.run([sys.executable, '-m', 'database.operations.init_development'],
                            cwd=root, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert Database(url).verify_schema() is True
