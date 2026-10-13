import os


os.environ.setdefault("ENTRY_ENV", "test")
os.environ.setdefault("ENTRY_ALLOW_SQLITE", "1")
os.environ.setdefault("ENTRY_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENTRY_SECRET_KEY", "test-secret-key-for-month-scope")
os.environ.setdefault("ENTRY_COOKIE_SECURE", "0")

import app.db.database as db_module  # noqa: E402
from sqlalchemy import select, update  # noqa: E402

from app.db.database import Database, metadata  # noqa: E402
from app.db.database import monthly_tasks, responsibilities, template_definitions  # noqa: E402


def test_template_detail_uses_version_effective_for_report_month(monkeypatch):
    monkeypatch.setattr(db_module, "previous_calendar_month", lambda now=None: "2026-09")
    database = Database("sqlite:///:memory:")
    database.reset_for_tests()

    database.create_template_version(1, "member_order_dimension_v1", "1.1", "2026-09")

    august_template = database.get_template_by_code("member_order_dimension_v1", report_month="2026-08")
    september_template = database.get_template_by_code("member_order_dimension_v1", report_month="2026-09")

    assert august_template["version"] == "1.0"
    assert august_template["effective_month"] == "2026-08"
    assert september_template["version"] == "1.1"
    assert september_template["effective_month"] == "2026-09"


def test_responsibilities_are_scoped_to_latest_effective_record_for_report_month(monkeypatch):
    monkeypatch.setattr(db_module, "previous_calendar_month", lambda now=None: "2026-09")
    database = Database("sqlite:///:memory:")
    database.reset_for_tests()

    database.set_responsibility(1, "member_order_dimension_v1", 3, "2026-09")

    august_rows = database.list_responsibilities(report_month="2026-08")
    september_rows = database.list_responsibilities(report_month="2026-09")

    august_member = next(row for row in august_rows if row["template"]["code"] == "member_order_dimension_v1")
    september_member = next(row for row in september_rows if row["template"]["code"] == "member_order_dimension_v1")

    assert august_member["effective_month"] == "2026-08"
    assert august_member["owner"]["username"] == "demo_member"
    assert september_member["effective_month"] == "2026-09"
    assert september_member["owner"]["username"] == "demo_cash"


def test_future_months_are_hidden_even_if_tasks_exist(monkeypatch):
    monkeypatch.setattr(db_module, "previous_calendar_month", lambda now=None: "2026-08")
    database = Database("sqlite:///:memory:")
    database.reset_for_tests()
    database.generate_tasks("2026-09", allow_future=True)

    context = database.get_reporting_context({"id": 1, "role": "admin"})

    assert database.list_task_months({"id": 1, "role": "admin"}) == ["2026-08"]
    assert [month["report_month"] for month in context["months"]] == ["2026-08"]
    assert database.list_tasks({"id": 1, "role": "admin"}, "2026-09") == []
    assert database.list_templates(report_month="2026-09") == []
    assert database.list_responsibilities(report_month="2026-09") == []


def test_sync_reporting_tasks_updates_only_unsubmitted_tasks(monkeypatch):
    monkeypatch.setattr(db_module, "previous_calendar_month", lambda now=None: "2026-08")
    database = Database("sqlite:///:memory:")
    database.reset_for_tests()

    with database.engine.begin() as connection:
        template_ids = dict(connection.execute(select(template_definitions.c.code, template_definitions.c.id)).all())
        member_template_id = template_ids["member_order_dimension_v1"]
        cash_flow_template_id = template_ids["cash_flow_detail_v1"]
        connection.execute(
            update(responsibilities)
            .where(responsibilities.c.template_id == member_template_id)
            .values(owner_user_id=3)
        )
        connection.execute(
            update(responsibilities)
            .where(responsibilities.c.template_id == cash_flow_template_id)
            .values(owner_user_id=2)
        )
        connection.execute(
            update(monthly_tasks)
            .where(
                monthly_tasks.c.template_id == cash_flow_template_id,
                monthly_tasks.c.report_month == "2026-08",
            )
            .values(status="pending_commit", current_batch_id=999)
        )

    result = database.sync_reporting_tasks(1, "2026-08")
    tasks = {
        task["template"]["code"]: task
        for task in database.list_tasks({"id": 1, "role": "admin"}, "2026-08")
    }

    assert result["sync_result"]["created_count"] == 0
    assert result["sync_result"]["updated_count"] == 1
    assert result["sync_result"]["skipped_count"] == 1
    assert tasks["member_order_dimension_v1"]["owner"]["username"] == "demo_cash"
    assert tasks["cash_flow_detail_v1"]["owner"]["username"] == "demo_cash"
    assert tasks["cash_flow_detail_v1"]["status"] == "pending_commit"


def test_admin_can_mark_monthly_task_not_required_and_restore(monkeypatch):
    from datetime import datetime
    monkeypatch.setattr(db_module, "utcnow", lambda: datetime(2026, 8, 15))
    monkeypatch.setattr(db_module, "previous_calendar_month", lambda now=None: "2026-08")
    database = Database("sqlite:///:memory:")
    database.reset_for_tests()

    task = next(
        item
        for item in database.list_tasks({"id": 1, "role": "admin"}, "2026-08")
        if item["template"]["code"] == "bad_debt_customer_v1"
    )

    marked = database.mark_task_not_required(1, task["id"])

    assert marked["status"] == "not_required"
    assert marked["access"]["writable"] is False
    assert marked["access"]["reason"] == "本月无需更新"
    tasks = database.list_tasks({"id": 1, "role": "admin"}, "2026-08")
    assert sum(item["status"] == "not_required" for item in tasks) == 1
    try:
        database.require_task_write_access({"id": 2, "role": "submitter"}, "bad_debt_customer_v1", "2026-08")
    except PermissionError as exc:
        assert str(exc) == "本月无需更新"
    else:
        raise AssertionError("not required task accepted uploads")

    restored = database.restore_required_task(1, task["id"])

    assert restored["status"] == "pending_submission"
    assert restored["access"]["writable"] is True
