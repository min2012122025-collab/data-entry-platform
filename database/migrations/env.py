from logging.config import fileConfig
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.db_safety import validate_database_target
from app.db.database import metadata


config = context.config
database_url = os.getenv("ENTRY_DATABASE_URL") or config.get_main_option("sqlalchemy.url")
validate_database_target(database_url, os.getenv("ENTRY_EXPECTED_DATABASE"))
# Alembic's ConfigParser treats percent-encoded URL credentials as interpolation.
config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def run_migrations_offline():
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    configuration = config.get_section(config.config_ini_section)
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
