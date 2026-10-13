import json
import sys
from pathlib import Path

from sqlalchemy import inspect, text

from app.container import database
from app.core.config import settings


def main(manifest_path: str) -> None:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    with database.engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != "20260907_0011":
            raise RuntimeError(f"数据库修订错误：{revision}")
        tables = set(inspect(connection).get_table_names())
        for name, expected in manifest.get("table_counts", {}).items():
            if name not in tables:
                raise RuntimeError(f"迁移后缺少表：{name}")
            actual = connection.execute(text(f"SELECT COUNT(*) FROM `{name}`")).scalar_one()
            if actual != expected:
                raise RuntimeError(f"表 {name} 记录数不一致：{actual} != {expected}")
    uploads = sum(1 for path in settings.upload_dir.rglob("*") if path.is_file())
    templates = sum(1 for path in settings.source_dir.rglob("*") if path.is_file())
    if uploads != manifest["upload_file_count"]:
        raise RuntimeError(f"上传文件数不一致：{uploads}")
    if templates != manifest["template_file_count"]:
        raise RuntimeError(f"模板文件数不一致：{templates}")
    print("migration_verify=passed")


if __name__ == "__main__":
    main(sys.argv[1])
