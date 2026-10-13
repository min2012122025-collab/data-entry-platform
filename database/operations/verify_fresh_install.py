"""Assert that a newly seeded production database contains no test/history data."""

from sqlalchemy import func, select

from app.db.database import (
    Database,
    audit_logs,
    data_connections,
    import_batches,
    monthly_tasks,
    previous_calendar_month,
    raw_files,
    reporting_periods,
    responsibilities,
    sessions,
    staging_records,
    target_write_operations,
    target_write_rows,
    template_definitions,
    template_table_mappings,
    template_versions,
    users,
    validation_errors,
)


EMPTY_TABLES = (
    sessions,
    reporting_periods,
    raw_files,
    import_batches,
    validation_errors,
    staging_records,
    audit_logs,
    data_connections,
    template_table_mappings,
    target_write_rows,
    target_write_operations,
)


def verify(database=None, verify_schema=True):
    database = database or Database()
    if verify_schema:
        database.verify_schema()
    expected_months = set()
    expected_templates = 0

    with database.engine.connect() as connection:
        admin_rows = connection.execute(select(users)).mappings().all()
        if len(admin_rows) != 1:
            raise RuntimeError(f"初始用户数量不正确：{len(admin_rows)}")
        admin = admin_rows[0]
        if (
            admin["username"] != "admin"
            or admin["role"] != "admin"
            or admin["disabled"]
            or not admin["must_change_password"]
        ):
            raise RuntimeError("初始 admin 账号状态不正确")

        template_count = connection.execute(
            select(func.count()).select_from(template_definitions)
        ).scalar_one()
        version_count = connection.execute(
            select(func.count()).select_from(template_versions)
        ).scalar_one()
        if template_count != expected_templates or version_count != expected_templates:
            raise RuntimeError(
                f"初始模板数量不正确：definitions={template_count}, versions={version_count}"
            )
        uploaded_template_count = connection.execute(
            select(func.count())
            .select_from(template_versions)
            .where(template_versions.c.template_file_path.is_not(None))
        ).scalar_one()
        if uploaded_template_count:
            raise RuntimeError("全新安装不应包含已上传模板文件")

        responsibility_rows = connection.execute(select(responsibilities)).mappings().all()
        if len(responsibility_rows) != expected_templates or any(
            row["owner_user_id"] is not None
            or row["effective_month"] != previous_calendar_month()
            for row in responsibility_rows
        ):
            raise RuntimeError("初始责任配置必须为上月生效且负责人待配置")

        task_rows = connection.execute(select(monthly_tasks)).mappings().all()
        expected_task_count = expected_templates * len(expected_months)
        if len(task_rows) != expected_task_count:
            raise RuntimeError(f"初始任务数量不正确：{len(task_rows)}")
        actual_months = {row["report_month"] for row in task_rows}
        if actual_months != expected_months:
            raise RuntimeError(f"初始任务月份不正确：{sorted(actual_months)}")
        if any(
            row["owner_user_id"] is not None
            or row["status"] != "pending_submission"
            or row["current_batch_id"] is not None
            for row in task_rows
        ):
            raise RuntimeError("初始任务必须为未分配、未提交的草稿")

        nonempty = {
            table.name: connection.execute(select(func.count()).select_from(table)).scalar_one()
            for table in EMPTY_TABLES
        }
        nonempty = {name: count for name, count in nonempty.items() if count}
        if nonempty:
            raise RuntimeError(f"全新安装包含不应存在的业务历史：{nonempty}")

    return {
        "admin": "admin",
        "templates": expected_templates,
        "tasks": expected_task_count,
        "months": sorted(expected_months),
        "history_rows": 0,
    }


def main():
    result = verify()
    for name, value in result.items():
        print(f"{name}={value}")
    print("fresh_install=passed")


if __name__ == "__main__":
    main()
