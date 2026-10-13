import os
import stat
from pathlib import Path

from app.core.config import settings
from app.db.database import Database


def read_old_key() -> str:
    value = os.getenv("ENTRY_OLD_SECRET_KEY_FILE")
    if not value:
        raise RuntimeError("缺少 ENTRY_OLD_SECRET_KEY_FILE")
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise RuntimeError("ENTRY_OLD_SECRET_KEY_FILE 必须指向已有的绝对路径")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise RuntimeError("ENTRY_OLD_SECRET_KEY_FILE 权限必须为 0600")
    secret = path.read_text(encoding="utf-8").strip()
    if not secret:
        raise RuntimeError("旧密钥文件不能为空")
    return secret


def main():
    settings.validate_process_environment()
    database = Database()
    database.verify_schema()
    admin = next((user for user in database.list_users() if user["role"] == "admin" and not user["disabled"]), None)
    if not admin:
        raise RuntimeError("缺少可用管理员账号，不能记录密钥轮换审计")
    result = database.rotate_data_connection_secrets(read_old_key(), actor_id=admin["id"])
    print(f"rotated_connections={result['rotated_connections']}")
    print("connection_tests_required=true")


if __name__ == "__main__":
    main()
