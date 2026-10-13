from app.core.config import settings
from app.core.db_safety import validate_database_target
from app.db.database import Database
from app.services.import_service import ImportService
from app.services.templates import BUILTIN_TABLE_MAPPINGS


def main():
    settings.validate_process_environment()
    database_name = validate_database_target(
        settings.database_url,
        settings.expected_database,
        allow_sqlite=settings.allow_sqlite,
    )
    database = Database()
    database.verify_schema()
    admin = next((user for user in database.list_users() if user["username"] == "admin"), None)
    if not admin:
        raise RuntimeError("缺少管理员账号，不能同步内置模板")

    service = ImportService(database, settings.upload_dir, source_dir=settings.source_dir)
    result = service.sync_builtin_template_files(admin, strict=True)
    connections = [
        item
        for item in database.list_data_connections()
        if item.get("write_capable")
    ]
    if len(connections) != 1:
        raise RuntimeError("必须且只能存在一个已启用并测试成功的数据连接")
    connection = connections[0]

    enabled = []
    for template in database.list_templates():
        mapping = BUILTIN_TABLE_MAPPINGS.get(template["code"])
        if not mapping:
            continue
        analysis = (template.get("template_file") or {}).get("analysis", {})
        sheets = analysis.get("sheets") or []
        definitions = mapping.get("sheets") or {sheets[0]["name"]: mapping}
        source_by_sheet = {item["name"]: item.get("fields") or [] for item in sheets}
        for sheet_name, definition in definitions.items():
            source_fields = source_by_sheet.get(sheet_name) or []
            expected_fields = list(definition["fields"])
            if set(source_fields) != set(expected_fields):
                missing = sorted(set(expected_fields) - set(source_fields))
                extra = sorted(set(source_fields) - set(expected_fields))
                raise RuntimeError(f"{template['code']}/{sheet_name} 模板字段与内置映射不一致；缺少={missing}；新增={extra}")
            existing = database.get_template_mapping(template["code"], template["version"], sheet_name)
            if existing:
                if existing["status"] == "enabled" and existing["connection"]["id"] == connection["id"] and existing["target_table"] == definition["target_table"] and existing["field_mapping"] == definition["fields"]:
                    continue
                raise RuntimeError(f"{template['code']}/{sheet_name} 已存在不同的入库映射，拒绝自动覆盖")
            saved = database.save_template_mapping(
                admin["id"], template["code"], template["version"], connection["id"],
                definition["target_table"], source_fields, definition["fields"], source_sheet_name=sheet_name,
            )
            if saved["status"] != "enabled":
                raise RuntimeError(f"{template['code']}/{sheet_name} 映射校验失败：{saved['validation'].get('errors', [])}")
        enabled.append(template["code"])

    if len(enabled) != len(BUILTIN_TABLE_MAPPINGS):
        raise RuntimeError("内置模板映射数量不完整")
    print(f"database={database_name}")
    print(f"template_files_synced={len(result['synced'])}")
    print(f"template_mappings_enabled={len(enabled)}")


if __name__ == "__main__":
    main()
