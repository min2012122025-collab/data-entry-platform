"""Initialize only the local SQLite demonstration database."""
from sqlalchemy import func, select
from alembic import command
from alembic.config import Config
from pathlib import Path
from app.core.config import settings
from app.db.database import Database, users

settings.validate_process_environment()
if settings.environment != 'development' or not settings.allow_sqlite or not settings.database_url.startswith('sqlite:///'):
    raise RuntimeError('Development initialization requires a local SQLite database')
database = Database()
command.upgrade(Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini')), 'head')
with database.engine.connect() as connection:
    empty = connection.execute(select(func.count()).select_from(users)).scalar_one() == 0
if empty:
    database.ensure_seed_data()
print('Local demonstration database ready.')
