from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db_safety import validate_database_target


def main():
    settings.validate_process_environment()
    database_name = validate_database_target(
        settings.database_url,
        settings.expected_database,
        allow_sqlite=settings.allow_sqlite,
    )
    url = make_url(settings.database_url)
    engine = create_engine(url, future=True, pool_pre_ping=True)
    with engine.connect() as connection:
        if url.get_backend_name() == "mysql":
            row = connection.execute(
                text("SELECT DATABASE() AS database_name, VERSION() AS server_version, CURRENT_USER() AS account")
            ).mappings().one()
            table_count = connection.execute(
                text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = :database_name"),
                {"database_name": database_name},
            ).scalar_one()
            print(f"database={row['database_name']}")
            print(f"server_version={row['server_version']}")
            print(f"account={row['account'].split('@', 1)[0]}")
            print(f"existing_tables={table_count}")
        else:
            connection.execute(text("SELECT 1"))
            print(f"database={database_name}")
            print("backend=sqlite")


if __name__ == "__main__":
    main()
