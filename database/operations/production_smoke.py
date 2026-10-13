from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.core.db_safety import validate_database_target
from app.db.database import Database, monthly_tasks, raw_files, responsibilities, template_definitions, users


def main():
    settings.validate_process_environment()
    database_name = validate_database_target(
        settings.database_url,
        settings.expected_database,
        allow_sqlite=settings.allow_sqlite,
    )
    database = Database()
    database.verify_schema()
    with database.engine.connect() as connection:
        counts = {
            "users": connection.execute(select(func.count()).select_from(users)).scalar_one(),
            "active_admins": connection.execute(
                select(func.count()).select_from(users).where(
                    users.c.role == "admin", users.c.disabled.is_(False)
                )
            ).scalar_one(),
            "templates": connection.execute(select(func.count()).select_from(template_definitions)).scalar_one(),
            "responsibilities": connection.execute(select(func.count()).select_from(responsibilities)).scalar_one(),
            "tasks": connection.execute(select(func.count()).select_from(monthly_tasks)).scalar_one(),
        }
        stored_paths = connection.execute(select(raw_files.c.stored_path)).scalars().all()

    if counts["users"] < 1 or counts["active_admins"] < 1 or counts["templates"] < 7:
        raise RuntimeError(f"基础数据不完整：{counts}")
    missing_directories = [
        str(path) for path in (settings.data_dir, settings.upload_dir, settings.source_dir) if not path.is_dir()
    ]
    if missing_directories:
        raise RuntimeError(f"生产文件目录不存在：{missing_directories}")
    temporary_paths = [
        path
        for path in stored_paths
        if str(path).startswith(("/tmp/", "/private/tmp/", "/private/var/"))
    ]
    if temporary_paths:
        raise RuntimeError(f"发现 {len(temporary_paths)} 条临时文件路径，请先完成文件迁移")
    if stored_paths:
        missing_files = sum(1 for path in stored_paths if not Path(path).is_file())
        if missing_files:
            raise RuntimeError(f"发现 {missing_files} 个原文件缺失")

    print(f"database={database_name}")
    for name, count in counts.items():
        print(f"{name}={count}")
    print(f"raw_files={len(stored_paths)}")
    print("production_smoke=passed")


if __name__ == "__main__":
    main()
