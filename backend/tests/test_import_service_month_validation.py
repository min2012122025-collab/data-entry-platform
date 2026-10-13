import os


os.environ.setdefault("ENTRY_ENV", "test")
os.environ.setdefault("ENTRY_ALLOW_SQLITE", "1")
os.environ.setdefault("ENTRY_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENTRY_SECRET_KEY", "test-secret-key-for-import-service")
os.environ.setdefault("ENTRY_COOKIE_SECURE", "0")

from app.services.import_service import ImportService  # noqa: E402


class FakeDatabase:
    def get_template_by_code(self, template_code):
        return {
            "code": template_code,
            "validation_rules": [],
            "date_fields": [],
        }

    def require_task_write_access(self, current_user, template_code, report_month):
        return None

    def create_import_batch(self, actor_id, actor_role, template_code, report_month, raw_file, summary, errors, records):
        return {
            "report_month": report_month,
            "summary": summary,
            "errors": errors,
            "records": records,
        }


class FakePipeline:
    def run(self, path, template_code, template=None, source_name=None, selected_report_month=None):
        return {
            "report_month": selected_report_month,
            "filename_report_month": "2026-07",
            "content_report_months": [],
            "content_report_months_by_sheet": {},
            "records": [
                {
                    "report_month": selected_report_month,
                    "sheet_name": "履约率分析",
                    "row_number": 2,
                    "payload": {"统计截至时间": "2026-07-31"},
                }
            ],
            "errors": [],
            "report": {
                "summary": {
                    "total_rows": 1,
                    "valid_rows": 1,
                    "blocking_errors": 0,
                    "warning_errors": 0,
                },
                "fields": ["统计截至时间"],
            },
        }


def test_task_upload_does_not_block_when_filename_month_differs_from_task_month(tmp_path):
    source = tmp_path / "履约率、应付账龄录入模板-2026.07-V1.xlsx"
    source.write_bytes(b"placeholder")
    service = ImportService(FakeDatabase(), tmp_path / "uploads")
    service.pipeline = FakePipeline()

    result = service.create_import(
        {"id": 2, "role": "submitter"},
        source,
        source.name,
        "ap_performance_aging_v1",
        report_month="2026-08",
    )

    assert result["report_month"] == "2026-08"
    assert result["summary"]["blocking_errors"] == 0
    assert not any(error["code"] == "filename_report_month_mismatch" for error in result["errors"])
