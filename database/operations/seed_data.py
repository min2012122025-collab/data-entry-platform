from app.core.config import settings
from app.core.db_safety import validate_database_target
from app.db.database import Database


def main():
    settings.validate_process_environment()
    database_name = validate_database_target(
        settings.database_url,
        settings.expected_database,
        allow_sqlite=settings.allow_sqlite,
    )
    database = Database()
    database.verify_schema()
    database.ensure_production_seed_data()
    print(f"通用录入平台 seed completed for database: {database_name}")


if __name__ == "__main__":
    main()
