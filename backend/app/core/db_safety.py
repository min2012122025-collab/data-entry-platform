import os

from sqlalchemy.engine import make_url


class DatabaseSafetyError(RuntimeError):
    pass


def validate_database_target(database_url, expected_database=None, allow_sqlite=None):
    url = make_url(str(database_url))
    backend = url.get_backend_name()
    if backend == "sqlite":
        sqlite_allowed = allow_sqlite if allow_sqlite is not None else os.getenv("ENTRY_ALLOW_SQLITE", "0") == "1"
        if not sqlite_allowed:
            raise DatabaseSafetyError("SQLite 仅允许用于明确启用的本地测试")
        return url.database
    if backend != "mysql":
        raise DatabaseSafetyError("正式数据库仅支持 MySQL")

    actual_database = url.database
    expected = expected_database or os.getenv("ENTRY_EXPECTED_DATABASE")
    if not actual_database:
        raise DatabaseSafetyError("MySQL 连接串必须包含 database/schema 名称")
    if not expected:
        raise DatabaseSafetyError("执行数据库写操作前必须设置 ENTRY_EXPECTED_DATABASE")
    if actual_database != expected:
        raise DatabaseSafetyError(f"连接目标库 {actual_database!r} 与预期库 {expected!r} 不一致，已拒绝执行")
    return actual_database


def validate_mysql_reset_target(database_url, allow_reset=False):
    url = make_url(str(database_url))
    if url.get_backend_name() != "mysql":
        raise DatabaseSafetyError("真实数据库重置验收仅支持 MySQL")
    if not allow_reset:
        raise DatabaseSafetyError("重置测试库前必须显式启用 ENTRY_MYSQL_TEST_ALLOW_RESET=1")
    database_name = url.database
    if not database_name or not database_name.endswith("_test"):
        raise DatabaseSafetyError("重置验收仅允许指向名称以 _test 结尾的专用测试库")
    return database_name
