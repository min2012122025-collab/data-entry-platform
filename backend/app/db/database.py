import json
import uuid
from collections import defaultdict
from threading import RLock
from time import monotonic
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    create_engine,
    delete,
    func,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.engine import make_url

from ..core.config import settings
from ..core.security import (
    decrypt_secret,
    decrypt_secret_with_key,
    encrypt_secret,
    encrypt_secret_with_key,
    hash_password,
    new_session_token,
    token_digest,
    verify_password,
)
from ..services.templates import BUILTIN_TABLE_MAPPINGS, TEMPLATES, default_validation_rules, describe_template


metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(64), nullable=False, unique=True),
    Column("display_name", String(128), nullable=False),
    Column("role", String(32), nullable=False),
    Column("department", String(128), nullable=False, default="业务部门"),
    Column("password_hash", String(255), nullable=False),
    Column("must_change_password", Boolean, nullable=False, default=False),
    Column("disabled", Boolean, nullable=False, default=False),
    Column("archived_at", DateTime),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("expires_at", DateTime, nullable=False),
    Column("revoked_at", DateTime),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

template_definitions = Table(
    "template_definitions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("code", String(128), nullable=False, unique=True),
    Column("name", String(255), nullable=False),
    Column("short_name", String(128), nullable=False),
    Column("description", Text, nullable=False),
    Column("status", String(32), nullable=False),
    Column("sort_order", Integer, nullable=False, default=100),
    Column("archived_at", DateTime),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

template_versions = Table(
    "template_versions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("template_id", Integer, ForeignKey("template_definitions.id"), nullable=False),
    Column("version", String(32), nullable=False),
    Column("effective_month", String(7), nullable=False),
    Column("sample_filename", String(512), nullable=False),
    Column("match_json", Text, nullable=False),
    Column("header_keywords_json", Text, nullable=False),
    Column("date_fields_json", Text, nullable=False),
    Column("required_fields_json", Text, nullable=False),
    Column("numeric_fields_json", Text, nullable=False),
    Column("validation_rules_json", Text, nullable=False, default="[]"),
    Column("template_file_original_name", String(512)),
    Column("template_file_path", Text),
    Column("template_file_sha256", String(64)),
    Column("template_file_size_bytes", Integer),
    Column("template_file_uploaded_at", DateTime),
    Column("template_file_analysis_json", Text, nullable=False, default="{}"),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint("template_id", "version", name="uq_template_version"),
)

responsibilities = Table(
    "responsibilities",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("template_id", Integer, ForeignKey("template_definitions.id"), nullable=False),
    Column("owner_user_id", Integer, ForeignKey("users.id")),
    Column("effective_month", String(7), nullable=False),
    Column("created_by_user_id", Integer, ForeignKey("users.id")),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint("template_id", "effective_month", name="uq_responsibility_month"),
)

reporting_periods = Table(
    "reporting_periods",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("report_month", String(7), nullable=False, unique=True),
    Column("status", String(32), nullable=False, default="draft"),
    Column("issued_by_user_id", Integer, ForeignKey("users.id")),
    Column("issued_at", DateTime),
    Column("closes_at", DateTime),
    Column("closed_by_user_id", Integer, ForeignKey("users.id")),
    Column("closed_at", DateTime),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)

monthly_tasks = Table(
    "monthly_tasks",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("template_id", Integer, ForeignKey("template_definitions.id"), nullable=False),
    Column("template_version_id", Integer, ForeignKey("template_versions.id"), nullable=False),
    Column("report_month", String(7), nullable=False),
    Column("owner_user_id", Integer, ForeignKey("users.id")),
    Column("status", String(32), nullable=False, default="pending_submission"),
    Column("current_batch_id", Integer),
    Column("reopened_until", DateTime),
    Column("reopened_by_user_id", Integer, ForeignKey("users.id")),
    Column("reopened_at", DateTime),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint("template_id", "report_month", name="uq_task_template_month"),
)

raw_files = Table(
    "raw_files",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("original_filename", String(512), nullable=False),
    Column("stored_path", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("uploaded_by_user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("metadata_json", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

import_batches = Table(
    "import_batches",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("template_id", Integer, ForeignKey("template_definitions.id"), nullable=False),
    Column("template_version_id", Integer, ForeignKey("template_versions.id"), nullable=False),
    Column("task_id", Integer, ForeignKey("monthly_tasks.id")),
    Column("raw_file_id", Integer, ForeignKey("raw_files.id"), nullable=False),
    Column("report_month", String(7)),
    Column("status", String(32), nullable=False),
    Column("submitted_by_user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("file_sha256", String(64), nullable=False),
    Column("active_commit_key", String(160), unique=True),
    Column("summary_json", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("committed_at", DateTime),
    Column("voided_at", DateTime),
    Column("void_reason", Text),
    Column("voided_by_user_id", Integer, ForeignKey("users.id")),
    Column("table_mapping_id", Integer, ForeignKey("template_table_mappings.id")),
    Column("target_write_count", Integer, nullable=False, default=0),
    Column("target_connection_id", Integer, ForeignKey("data_connections.id")),
    Column("target_schema", String(128)),
    Column("target_table", String(128)),
    Column("target_field_mapping_json", Text),
    Column("target_mappings_json", Text),
)

validation_errors = Table(
    "validation_errors",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("import_batch_id", Integer, ForeignKey("import_batches.id"), nullable=False),
    Column("row_number", Integer),
    Column("cell", String(64)),
    Column("field", String(128)),
    Column("code", String(128), nullable=False),
    Column("message", Text, nullable=False),
    Column("suggestion", Text, nullable=False),
    Column("blocking", Boolean, nullable=False),
)

staging_records = Table(
    "staging_records",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("import_batch_id", Integer, ForeignKey("import_batches.id"), nullable=False),
    Column("report_month", String(7), nullable=False),
    Column("sheet_name", String(255), nullable=False),
    Column("row_number", Integer, nullable=False),
    Column("payload_json", Text, nullable=False),
)

audit_logs = Table(
    "audit_logs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("actor_user_id", Integer, ForeignKey("users.id")),
    Column("action", String(128), nullable=False),
    Column("target_type", String(64), nullable=False),
    Column("target_id", String(64), nullable=False),
    Column("message", Text, nullable=False),
    Column("payload_json", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
)

data_connections = Table(
    "data_connections",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(128), nullable=False),
    Column("connection_type", String(32), nullable=False, default="mysql"),
    Column("host", String(255), nullable=False),
    Column("port", Integer, nullable=False, default=3306),
    Column("username", String(128), nullable=False),
    Column("password_secret", Text, nullable=False),
    Column("database_name", String(128)),
    Column("status", String(32), nullable=False, default="active"),
    Column("last_test_status", String(32)),
    Column("last_test_message", Text),
    Column("last_tested_at", DateTime),
    Column("server_uuid", String(64)),
    Column("same_instance", Boolean, nullable=False, default=False),
    Column("created_by_user_id", Integer, ForeignKey("users.id")),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)

template_table_mappings = Table(
    "template_table_mappings",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("template_version_id", Integer, ForeignKey("template_versions.id"), nullable=False),
    Column("source_sheet_name", String(255)),
    Column("data_connection_id", Integer, ForeignKey("data_connections.id"), nullable=False),
    Column("target_schema", String(128), nullable=False),
    Column("target_table", String(128), nullable=False),
    Column("is_active", Boolean, nullable=False, default=True),
    Column("archived_at", DateTime),
    Column("field_mapping_json", Text, nullable=False, default="{}"),
    Column("status", String(32), nullable=False, default="draft"),
    Column("last_validation_json", Text, nullable=False, default="{}"),
    Column("last_validated_at", DateTime),
    Column("last_written_at", DateTime),
    Column("created_by_user_id", Integer, ForeignKey("users.id")),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint(
        "template_version_id",
        "source_sheet_name",
        "data_connection_id",
        "target_schema",
        "target_table",
        name="uq_template_table_mapping_target",
    ),
)

target_write_rows = Table(
    "target_write_rows",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("import_batch_id", Integer, ForeignKey("import_batches.id"), nullable=False),
    Column("table_mapping_id", Integer, ForeignKey("template_table_mappings.id"), nullable=False),
    Column("row_index", Integer, nullable=False),
    Column("primary_key_json", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint("import_batch_id", "row_index", name="uq_target_write_batch_row"),
)

target_write_operations = Table(
    "target_write_operations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("operation_key", String(36), nullable=False, unique=True),
    Column("operation_type", String(32), nullable=False),
    Column("batch_id", Integer, ForeignKey("import_batches.id"), nullable=False),
    Column("previous_batch_id", Integer, ForeignKey("import_batches.id")),
    Column("table_mapping_id", Integer, ForeignKey("template_table_mappings.id"), nullable=False),
    Column("data_connection_id", Integer, ForeignKey("data_connections.id"), nullable=False),
    Column("target_schema", String(128), nullable=False),
    Column("target_table", String(128), nullable=False),
    Column("mapping_snapshot_json", Text),
    Column("expected_row_count", Integer, nullable=False),
    Column("expected_sources_json", Text().with_variant(LONGTEXT(), "mysql", "mariadb"), nullable=False),
    Column("state", String(32), nullable=False),
    Column("attempt_count", Integer, nullable=False, default=0),
    Column("last_error", Text),
    Column("active_scope_key", String(160), unique=True),
    Column("target_committed_at", DateTime),
    Column("finalized_at", DateTime),
    Column("created_by_user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)

for _table in metadata.tables.values():
    _table.dialect_options["mysql"]["engine"] = "InnoDB"
    _table.dialect_options["mysql"]["charset"] = "utf8mb4"


SEED_USERS = [
    ("admin", "管理员", "admin", "业务部门", False),
    ("demo_member", "示例填报员甲", "submitter", "业务部门", False),
    ("demo_cash", "示例填报员乙", "submitter", "业务部门", False),
    ("demo_payroll", "示例填报员丙", "submitter", "业务部门", False),
    ("demo_income", "示例填报员丁", "submitter", "业务部门", False),
]


def utcnow():
    return datetime.utcnow()


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def shanghai_now():
    return utcnow().replace(tzinfo=timezone.utc).astimezone(SHANGHAI_TZ)


def previous_calendar_month(now=None):
    current = now or shanghai_now()
    year, month = current.year, current.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def current_calendar_month(now=None):
    current = now or shanghai_now()
    return f"{current.year:04d}-{current.month:02d}"


def visible_report_month_cutoff(now=None):
    return previous_calendar_month(now)


def next_calendar_month(report_month):
    year, month = (int(part) for part in report_month.split("-"))
    return f"{year + (month == 12):04d}-{1 if month == 12 else month + 1:02d}"


def default_period_closes_at(report_month):
    year, month = (int(part) for part in report_month.split("-"))
    next_year, next_month = year, month + 1
    if next_month == 13:
        next_year, next_month = year + 1, 1
    local_deadline = datetime(
        next_year,
        next_month,
        monthrange(next_year, next_month)[1],
        23,
        59,
        59,
        tzinfo=SHANGHAI_TZ,
    )
    return local_deadline.astimezone(timezone.utc).replace(tzinfo=None)


def normalize_utc_datetime(value):
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def utc_iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat() if value else None


TARGET_WRITE_CHUNK_SIZE = 500
MAPPING_METADATA_CACHE_TTL_SECONDS = 60


def chunked(values, size=TARGET_WRITE_CHUNK_SIZE):
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def primary_key_signature(values):
    return tuple((name, str(values[name])) for name in sorted(values))


def normalize_database_url(value):
    if not value:
        raise RuntimeError("缺少 ENTRY_DATABASE_URL，生产数据库连接必须由外部环境提供")
    text = str(value)
    if "://" in text:
        return text
    return f"sqlite:///{Path(text)}"


class Database:
    def __init__(self, database_url_or_path=None):
        self.database_url = normalize_database_url(database_url_or_path or settings.database_url)
        if self.database_url.startswith("sqlite") and not settings.allow_sqlite:
            raise ValueError("SQLite is allowed only when ENTRY_ALLOW_SQLITE=1")
        self.engine = create_engine(self.database_url, future=True, pool_pre_ping=True)
        self.dialect = self.engine.dialect.name
        self._mapping_metadata_cache = {}
        self._mapping_metadata_cache_lock = RLock()

    @property
    def masked_database_url(self):
        return make_url(self.database_url).render_as_string(hide_password=True)

    def health(self):
        with self.engine.connect() as connection:
            connection.execute(select(1))
        return {"database_url": self.masked_database_url, "dialect": self.dialect}

    def verify_schema(self):
        settings.validate_runtime(self.database_url)
        existing = set(inspect(self.engine).get_table_names())
        required = set(metadata.tables) | {"alembic_version"}
        missing = sorted(required - existing)
        if missing:
            raise RuntimeError(f"数据库迁移未完成，缺少表：{', '.join(missing)}")
        return True

    def reset_for_tests(self):
        metadata.drop_all(self.engine)
        metadata.create_all(self.engine)
        self.ensure_seed_data()

    def ensure_production_seed_data(self):
        with self.engine.begin() as connection:
            admin = connection.execute(select(users).where(users.c.username == "admin")).mappings().first()
            if not admin:
                admin_id = connection.execute(
                    insert(users).values(
                        username="admin",
                        display_name="管理员",
                        role="admin",
                        department="业务部门",
                        password_hash=hash_password(settings.seed_password("admin", self.dialect)),
                        must_change_password=True,
                        disabled=False,
                    )
                ).inserted_primary_key[0]
            else:
                admin_id = admin["id"]
            # Business templates are created by administrators, never seeded in production.
            return

    def ensure_seed_data(self):
        with self.engine.begin() as connection:
            user_ids = self._seed_users(connection)
            template_ids = self._seed_templates(connection)
            self._seed_responsibilities(connection, user_ids, template_ids)
            for month in ("2026-07", "2026-08"):
                self._generate_tasks(connection, month)
                if not connection.execute(
                    select(reporting_periods.c.id).where(reporting_periods.c.report_month == month)
                ).first():
                    is_issued = month <= previous_calendar_month()
                    connection.execute(
                        insert(reporting_periods).values(
                            report_month=month,
                            status="issued" if is_issued else "draft",
                            issued_by_user_id=user_ids.get("admin") if is_issued else None,
                            issued_at=utcnow() if is_issued else None,
                            closes_at=default_period_closes_at(month) if is_issued else None,
                            updated_at=utcnow(),
                        )
                    )

    def _seed_users(self, connection):
        ids = {}
        for username, display_name, role, department, must_change in SEED_USERS:
            row = connection.execute(select(users).where(users.c.username == username)).mappings().first()
            if row:
                ids[username] = row["id"]
                continue
            result = connection.execute(
                insert(users).values(
                    username=username,
                    display_name=display_name,
                    role=role,
                    department=department,
                    password_hash=hash_password(settings.seed_password(username, self.dialect)),
                    must_change_password=must_change,
                    disabled=False,
                )
            )
            ids[username] = result.inserted_primary_key[0]
        return ids

    def _seed_templates(self, connection):
        ids = {}
        for template in TEMPLATES:
            row = connection.execute(
                select(template_definitions).where(template_definitions.c.code == template["code"])
            ).mappings().first()
            values = {
                "code": template["code"],
                "name": template["name"],
                "short_name": template["short_name"],
                "description": template["description"],
                "status": template["status"],
                "sort_order": template["sort_order"],
            }
            if row:
                ids[template["code"]] = row["id"]
            else:
                result = connection.execute(insert(template_definitions).values(**values))
                ids[template["code"]] = result.inserted_primary_key[0]
            template_id = ids[template["code"]]
            version_row = connection.execute(
                select(template_versions).where(
                    template_versions.c.template_id == template_id,
                    template_versions.c.version == template["version"],
                )
            ).mappings().first()
            version_values = {
                "template_id": template_id,
                "version": template["version"],
                "effective_month": template["effective_month"],
                "sample_filename": template["sample_filename"],
                "match_json": json.dumps(template.get("match", []), ensure_ascii=False),
                "header_keywords_json": json.dumps(template.get("header_keywords", []), ensure_ascii=False),
                "date_fields_json": json.dumps(template.get("date_fields", []), ensure_ascii=False),
                "required_fields_json": json.dumps(template.get("required_fields", []), ensure_ascii=False),
                "numeric_fields_json": json.dumps(template.get("numeric_fields", []), ensure_ascii=False),
                "validation_rules_json": "[]",
                "template_file_analysis_json": "{}",
            }
            if not version_row:
                connection.execute(insert(template_versions).values(**version_values))
        return ids

    def _seed_responsibilities(self, connection, user_ids, template_ids):
        for template in TEMPLATES:
            template_id = template_ids[template["code"]]
            owner_id = user_ids.get(template["default_owner"])
            exists = connection.execute(
                select(responsibilities.c.id).where(
                    responsibilities.c.template_id == template_id,
                    responsibilities.c.effective_month == template["effective_month"],
                )
            ).first()
            if not exists:
                connection.execute(
                    insert(responsibilities).values(
                        template_id=template_id,
                        owner_user_id=owner_id,
                        effective_month=template["effective_month"],
                        created_by_user_id=user_ids.get("admin"),
                    )
                )

    def _generate_tasks(self, connection, report_month):
        result = {"created": [], "updated": [], "skipped": []}
        template_rows = connection.execute(
            select(template_definitions).where(
                template_definitions.c.status == "enabled",
                template_definitions.c.archived_at.is_(None),
            ).order_by(template_definitions.c.sort_order)
        ).mappings().all()
        for template in template_rows:
            version = self._version_for_month(connection, template["id"], report_month)
            if not version:
                continue
            owner_id = self._owner_for_month(connection, template["id"], report_month)
            task = connection.execute(
                select(monthly_tasks).where(
                    monthly_tasks.c.template_id == template["id"],
                    monthly_tasks.c.report_month == report_month,
                )
            ).mappings().first()
            values = {
                "template_id": template["id"],
                "template_version_id": version["id"],
                "report_month": report_month,
                "owner_user_id": owner_id,
                "updated_at": utcnow(),
            }
            item = {
                "template_code": template["code"],
                "template_name": template["short_name"],
                "task_id": task["id"] if task else None,
                "owner_user_id": owner_id,
                "template_version_id": version["id"],
            }
            if task:
                changed = (
                    task["template_version_id"] != version["id"]
                    or task["owner_user_id"] != owner_id
                )
                if changed and task["status"] == "pending_submission" and task["current_batch_id"] is None:
                    connection.execute(update(monthly_tasks).where(monthly_tasks.c.id == task["id"]).values(**values))
                    result["updated"].append(item)
                elif changed:
                    result["skipped"].append({
                        **item,
                        "status": task["status"],
                        "current_batch_id": task["current_batch_id"],
                        "reason": "任务已有上传或处理记录，已保留原配置",
                    })
            else:
                created = connection.execute(insert(monthly_tasks).values(**values, status="pending_submission"))
                result["created"].append({**item, "task_id": created.inserted_primary_key[0]})
        return result

    def generate_tasks(self, report_month, allow_future=False):
        self._validate_report_month(report_month)
        if not allow_future and report_month > visible_report_month_cutoff():
            raise ValueError("不能生成未来月份任务")
        with self.engine.begin() as connection:
            self._generate_tasks(connection, report_month)
            self.audit(connection, None, "tasks.generate", "month", report_month, f"生成 {report_month} 月度任务", {})

    def sync_reporting_tasks(self, actor_id, report_month):
        self._validate_report_month(report_month)
        if report_month > visible_report_month_cutoff():
            raise ValueError("不能同步未来月份任务")
        with self.engine.begin() as connection:
            period = self._period_row(connection, report_month, for_update=True)
            if not period or period["status"] == "draft":
                raise ValueError("该月份任务尚未下发，请先下发任务")
            sync_result = self._generate_tasks(connection, report_month)
            sync_result.update(
                {
                    "created_count": len(sync_result["created"]),
                    "updated_count": len(sync_result["updated"]),
                    "skipped_count": len(sync_result["skipped"]),
                }
            )
            self.audit(
                connection,
                actor_id,
                "tasks.sync",
                "month",
                report_month,
                f"同步 {report_month} 任务配置",
                sync_result,
            )
            period_payload = self._period_payload(connection, report_month)
            period_payload["sync_result"] = sync_result
            return period_payload

    @staticmethod
    def _validate_report_month(report_month):
        try:
            parsed = datetime.strptime(report_month, "%Y-%m")
        except (TypeError, ValueError) as exc:
            raise ValueError("填报月份格式不正确") from exc
        if parsed.strftime("%Y-%m") != report_month:
            raise ValueError("填报月份格式不正确")

    def _period_row(self, connection, report_month, for_update=False):
        query = select(reporting_periods).where(reporting_periods.c.report_month == report_month)
        if for_update and self.dialect == "mysql":
            query = query.with_for_update()
        return connection.execute(query).mappings().first()

    def _task_access_from_period(self, task, period, now=None):
        now = now or utcnow()
        if task.get("status") == "not_required":
            return {
                "writable": False,
                "state": "closed",
                "reason": "本月无需更新",
                "deadline": None,
            }
        if task.get("status") == "cancelled":
            return {
                "writable": False,
                "state": "closed",
                "reason": "模板已停用，该空任务已取消",
                "deadline": None,
            }
        reopened_until = task.get("reopened_until")
        if reopened_until and reopened_until > now:
            return {
                "writable": True,
                "state": "reopened",
                "reason": "当前任务已开放补报",
                "deadline": utc_iso(reopened_until),
            }
        if not period or period["status"] == "draft":
            return {
                "writable": False,
                "state": "draft",
                "reason": "该月份任务尚未下发",
                "deadline": None,
            }
        if period["status"] == "closed" or period["closed_at"]:
            return {
                "writable": False,
                "state": "closed",
                "reason": "该月份已封板，如需补报请联系管理员",
                "deadline": utc_iso(period["closes_at"]),
            }
        if not period["closes_at"] or period["closes_at"] <= now:
            return {
                "writable": False,
                "state": "closed",
                "reason": "该月份已超过填报截止时间，如需补报请联系管理员",
                "deadline": utc_iso(period["closes_at"]),
            }
        return {
            "writable": True,
            "state": "open",
            "reason": "任务填报中",
            "deadline": utc_iso(period["closes_at"]),
        }

    def _task_access(self, connection, task, now=None):
        return self._task_access_from_period(task, self._period_row(connection, task["report_month"]), now=now)

    def _ensure_task_writable(self, connection, task):
        access = self._task_access(connection, task)
        if not access["writable"]:
            raise PermissionError(access["reason"])
        return access

    def require_task_write_access(self, current_user, template_code, report_month, connection=None):
        owns_connection = connection is None
        connection = connection or self.engine.connect()
        try:
            query = (
                select(monthly_tasks)
                .join(template_definitions, monthly_tasks.c.template_id == template_definitions.c.id)
                .where(template_definitions.c.code == template_code, monthly_tasks.c.report_month == report_month)
            )
            if self.dialect == "mysql" and connection.in_transaction():
                query = query.with_for_update()
            task = connection.execute(query).mappings().first()
            if not task:
                raise PermissionError("当前模板和月份没有填报任务")
            if current_user["role"] != "admin":
                if task["owner_user_id"] is None:
                    raise PermissionError("当前任务尚未配置负责人")
                if task["owner_user_id"] != current_user["id"]:
                    raise PermissionError("你不是当前模板和月份的任务负责人")
            self._ensure_task_writable(connection, task)
            return task
        finally:
            if owns_connection:
                connection.close()

    def _template_version_commit_readiness(self, connection, version_id, live_validate=False):
        version = connection.execute(
            select(template_versions).where(template_versions.c.id == version_id)
        ).mappings().first()
        if not version:
            return {"ready": False, "blockers": ["缺少有效模板版本"], "target": None, "mapping_ready": False, "connection_ready": False}
        blockers = []
        analysis = json.loads(version.get("template_file_analysis_json") or "{}")
        sheets = [
            {"name": item.get("name"), "fields": item.get("fields") or []}
            for item in analysis.get("sheets") or []
            if item.get("name")
        ]
        source_fields = analysis.get("fields") or []
        if not version.get("template_file_path"):
            blockers.append("模板文件尚未上传")
        elif analysis.get("confirmed") is not True:
            blockers.append("模板文件表头尚未确认")
        elif not source_fields:
            blockers.append("模板文件没有可映射字段")
        mappings = connection.execute(
            select(template_table_mappings).where(
                template_table_mappings.c.template_version_id == version_id,
                template_table_mappings.c.is_active.is_(True),
                template_table_mappings.c.archived_at.is_(None),
            )
        ).mappings().all()
        mapping_by_sheet = {item["source_sheet_name"]: item for item in mappings if item.get("source_sheet_name")}
        if len(sheets) == 1 and None not in mapping_by_sheet:
            legacy = next((item for item in mappings if not item.get("source_sheet_name")), None)
            if legacy:
                mapping_by_sheet[sheets[0]["name"]] = legacy
        targets = []
        connection_ids = set()
        connection_ready = True
        for sheet in sheets:
            mapping = mapping_by_sheet.get(sheet["name"])
            if not mapping or mapping["status"] != "enabled":
                blockers.append(f"工作表 {sheet['name']} 未配置有效的目标表映射")
                connection_ready = False
                continue
            data_connection = connection.execute(
                select(data_connections).where(data_connections.c.id == mapping["data_connection_id"])
            ).mappings().first()
            connection_ids.add(mapping["data_connection_id"])
            if not data_connection or data_connection["status"] != "active" or data_connection["last_test_status"] != "success":
                blockers.append(f"工作表 {sheet['name']} 的目标数据库连接未启用或尚未测试成功")
                connection_ready = False
            elif self._connection_credential_status(data_connection) != "ready":
                blockers.append(f"工作表 {sheet['name']} 的目标数据库连接凭据不可用，请管理员重新保存密码")
                connection_ready = False
            elif live_validate and sheet["fields"]:
                validation = self._mapping_validation_details(
                    mapping, data_connection, sheet["fields"], refresh=True
                )
                blockers.extend(f"工作表 {sheet['name']}：{error}" for error in validation["errors"])
            elif data_connection:
                try:
                    self._validate_target_host(data_connection)
                    self._validate_target_schema(data_connection.get("database_name"))
                except ValueError as exc:
                    blockers.append(f"工作表 {sheet['name']}：{exc}")
                    connection_ready = False
            targets.append({
                "sheet_name": sheet["name"],
                "mapping_id": mapping["id"],
                "connection_id": mapping["data_connection_id"],
                "connection_name": data_connection["name"] if data_connection else None,
                "database_name": mapping["target_schema"],
                "table_name": mapping["target_table"],
            })
        if len(connection_ids) > 1:
            blockers.append("同一模板的所有工作表必须使用同一个数据连接")
            connection_ready = False
        target = targets[0] if targets else None
        return {
            "ready": not blockers,
            "blockers": list(dict.fromkeys(blockers)),
            "target": target,
            "targets": targets,
            "mapping_ready": bool(sheets) and len(targets) == len(sheets) and all(mapping_by_sheet.get(sheet["name"], {}).get("status") == "enabled" for sheet in sheets),
            "connection_ready": bool(targets) and connection_ready,
        }

    def get_template_version_commit_readiness(self, template_code, version, live_validate=True):
        with self.engine.connect() as connection:
            version_row = connection.execute(
                select(template_versions.c.id)
                .join(template_definitions, template_definitions.c.id == template_versions.c.template_id)
                .where(template_definitions.c.code == template_code, template_versions.c.version == version)
            ).first()
            if not version_row:
                return {"ready": False, "blockers": ["缺少有效模板版本"], "target": None, "targets": []}
            return self._template_version_commit_readiness(connection, version_row[0], live_validate=live_validate)

    def _reporting_period_readiness(self, connection, report_month, live_validate=False):
        templates = connection.execute(
            select(template_definitions)
            .where(template_definitions.c.status == "enabled", template_definitions.c.archived_at.is_(None))
            .order_by(template_definitions.c.sort_order)
        ).mappings().all()
        items = []
        for template in templates:
            version = self._version_for_month(connection, template["id"], report_month)
            owner_id = self._owner_for_month(connection, template["id"], report_month)
            if version:
                version_readiness = self._template_version_commit_readiness(
                    connection, version["id"], live_validate=live_validate
                )
                blockers = list(version_readiness["blockers"])
            else:
                version_readiness = {"ready": False, "target": None, "mapping_ready": False, "connection_ready": False}
                blockers = ["缺少有效模板版本"]
            if not owner_id:
                blockers.insert(0, "缺少负责人")
            items.append(
                {
                    "template_code": template["code"],
                    "template_name": template["short_name"],
                    "version": version["version"] if version else None,
                    "owner_ready": bool(owner_id),
                    "template_file_ready": bool(version and version.get("template_file_path")),
                    "header_confirmed": bool(
                        version
                        and json.loads(version.get("template_file_analysis_json") or "{}").get("confirmed") is True
                    ),
                    "mapping_ready": bool(version_readiness.get("mapping_ready")),
                    "connection_ready": bool(version_readiness.get("connection_ready")),
                    "target": version_readiness.get("target"),
                    "targets": version_readiness.get("targets", []),
                    "blockers": list(dict.fromkeys(blockers)),
                }
            )
        return {"report_month": report_month, "ready": all(not item["blockers"] for item in items), "items": items}

    def get_reporting_period_readiness(self, report_month, live_validate=False):
        self._validate_report_month(report_month)
        with self.engine.connect() as connection:
            return self._json_ready(
                self._reporting_period_readiness(connection, report_month, live_validate=live_validate)
            )

    def issue_reporting_period(self, actor_id, report_month, closes_at):
        self._validate_report_month(report_month)
        if report_month > visible_report_month_cutoff():
            raise ValueError("不能下发未来月份任务")
        closes_at = normalize_utc_datetime(closes_at)
        if not closes_at or closes_at <= utcnow():
            raise ValueError("填报截止时间必须晚于当前时间")
        with self.engine.begin() as connection:
            period = self._period_row(connection, report_month, for_update=True)
            if period and period["status"] != "draft":
                raise ValueError("该月份任务已经下发，不能重复下发")
            readiness = self._reporting_period_readiness(connection, report_month, live_validate=True)
            if not readiness["ready"]:
                errors = [
                    f"{item['template_name']}：{'、'.join(item['blockers'])}"
                    for item in readiness["items"]
                    if item["blockers"]
                ]
                raise ValueError("；".join(errors))
            self._generate_tasks(connection, report_month)
            values = {
                "status": "issued",
                "issued_by_user_id": actor_id,
                "issued_at": utcnow(),
                "closes_at": closes_at,
                "closed_by_user_id": None,
                "closed_at": None,
                "updated_at": utcnow(),
            }
            if period:
                connection.execute(update(reporting_periods).where(reporting_periods.c.id == period["id"]).values(**values))
            else:
                connection.execute(insert(reporting_periods).values(report_month=report_month, **values))
            self.audit(connection, actor_id, "tasks.issue", "month", report_month, f"下发 {report_month} 填报任务", {"closes_at": closes_at.isoformat()})
        return self.get_reporting_period(report_month)

    def update_reporting_deadline(self, actor_id, report_month, closes_at):
        closes_at = normalize_utc_datetime(closes_at)
        if not closes_at or closes_at <= utcnow():
            raise ValueError("填报截止时间必须晚于当前时间")
        with self.engine.begin() as connection:
            period = self._period_row(connection, report_month, for_update=True)
            if not period or period["status"] == "draft":
                raise ValueError("该月份任务尚未下发")
            if period["status"] == "closed" or period["closed_at"] or not period["closes_at"] or period["closes_at"] <= utcnow():
                raise ValueError("已封板月份不能整体延长，请为指定模板开放补报")
            connection.execute(
                update(reporting_periods).where(reporting_periods.c.id == period["id"]).values(closes_at=closes_at, updated_at=utcnow())
            )
            self.audit(connection, actor_id, "tasks.deadline_update", "month", report_month, "调整填报截止时间", {"closes_at": closes_at.isoformat()})
        return self.get_reporting_period(report_month)

    def close_reporting_period(self, actor_id, report_month):
        with self.engine.begin() as connection:
            period = self._period_row(connection, report_month, for_update=True)
            if not period or period["status"] == "draft":
                raise ValueError("该月份任务尚未下发")
            if period["status"] == "closed":
                raise ValueError("该月份已经封板")
            connection.execute(
                update(reporting_periods).where(reporting_periods.c.id == period["id"]).values(
                    status="closed", closed_by_user_id=actor_id, closed_at=utcnow(), updated_at=utcnow()
                )
            )
            self.audit(connection, actor_id, "tasks.close", "month", report_month, f"封板 {report_month} 填报任务", {})
        return self.get_reporting_period(report_month)

    def reopen_task(self, actor_id, task_id, closes_at):
        closes_at = normalize_utc_datetime(closes_at)
        if not closes_at or closes_at <= utcnow():
            raise ValueError("补报截止时间必须晚于当前时间")
        with self.engine.begin() as connection:
            query = select(monthly_tasks).where(monthly_tasks.c.id == task_id)
            if self.dialect == "mysql":
                query = query.with_for_update()
            task = connection.execute(query).mappings().first()
            if not task:
                raise ValueError("任务不存在")
            base = self._task_access(connection, {**task, "reopened_until": None})
            if base["state"] == "draft":
                raise ValueError("未下发任务不能开放补报，请先下发该月份")
            if base["writable"]:
                raise ValueError("当前任务仍在正常填报期内，无需开放补报")
            connection.execute(update(monthly_tasks).where(monthly_tasks.c.id == task_id).values(
                reopened_until=closes_at, reopened_by_user_id=actor_id, reopened_at=utcnow(), updated_at=utcnow()
            ))
            self.audit(connection, actor_id, "tasks.reopen", "monthly_task", str(task_id), "开放任务补报", {"closes_at": closes_at.isoformat()})
        return self.get_task({"id": actor_id, "role": "admin"}, task_id)

    def close_reopened_task(self, actor_id, task_id):
        with self.engine.begin() as connection:
            query = select(monthly_tasks).where(monthly_tasks.c.id == task_id)
            if self.dialect == "mysql":
                query = query.with_for_update()
            task = connection.execute(query).mappings().first()
            if not task:
                raise ValueError("任务不存在")
            if not task["reopened_until"] or task["reopened_until"] <= utcnow():
                raise ValueError("当前任务不在补报开放状态")
            connection.execute(update(monthly_tasks).where(monthly_tasks.c.id == task_id).values(reopened_until=None, updated_at=utcnow()))
            self.audit(connection, actor_id, "tasks.reopen_close", "monthly_task", str(task_id), "提前封板补报任务", {})
        return self.get_task({"id": actor_id, "role": "admin"}, task_id)

    def mark_task_not_required(self, actor_id, task_id):
        with self.engine.begin() as connection:
            query = select(monthly_tasks).where(monthly_tasks.c.id == task_id)
            if self.dialect == "mysql":
                query = query.with_for_update()
            task = connection.execute(query).mappings().first()
            if not task:
                raise ValueError("任务不存在")
            if task["status"] == "not_required":
                raise ValueError("当前任务已标记为本月无需更新")
            if task["status"] != "pending_submission" or task["current_batch_id"] is not None:
                raise ValueError("已有上传或处理记录的任务不能标记为无需更新")
            connection.execute(
                update(monthly_tasks)
                .where(monthly_tasks.c.id == task_id)
                .values(status="not_required", reopened_until=None, updated_at=utcnow())
            )
            self.audit(connection, actor_id, "tasks.not_required", "monthly_task", str(task_id), "标记本月无需更新", {})
        return self.get_task({"id": actor_id, "role": "admin"}, task_id)

    def restore_required_task(self, actor_id, task_id):
        with self.engine.begin() as connection:
            query = select(monthly_tasks).where(monthly_tasks.c.id == task_id)
            if self.dialect == "mysql":
                query = query.with_for_update()
            task = connection.execute(query).mappings().first()
            if not task:
                raise ValueError("任务不存在")
            if task["status"] != "not_required":
                raise ValueError("当前任务未标记为无需更新")
            connection.execute(
                update(monthly_tasks)
                .where(monthly_tasks.c.id == task_id)
                .values(status="pending_submission", updated_at=utcnow())
            )
            self.audit(connection, actor_id, "tasks.required_restore", "monthly_task", str(task_id), "恢复本月更新", {})
        return self.get_task({"id": actor_id, "role": "admin"}, task_id)

    def authenticate(self, username, password):
        with self.engine.connect() as connection:
            row = connection.execute(select(users).where(users.c.username == username)).mappings().first()
            if not row or row["disabled"] or row.get("archived_at") or not verify_password(password, row["password_hash"]):
                return None
            return self.public_user(row)

    def create_session(self, user_id):
        token = new_session_token()
        with self.engine.begin() as connection:
            connection.execute(
                insert(sessions).values(
                    token_hash=token_digest(token),
                    user_id=user_id,
                    expires_at=utcnow() + timedelta(hours=settings.session_hours),
                )
            )
        return token

    def get_user_by_session(self, token):
        if not token:
            return None
        with self.engine.connect() as connection:
            row = connection.execute(
                select(users)
                .select_from(sessions.join(users, sessions.c.user_id == users.c.id))
                .where(
                    sessions.c.token_hash == token_digest(token),
                    sessions.c.revoked_at.is_(None),
                    sessions.c.expires_at > utcnow(),
                    users.c.disabled.is_(False),
                    users.c.archived_at.is_(None),
                )
            ).mappings().first()
            return self.public_user(row) if row else None

    def revoke_session(self, token):
        if not token:
            return
        with self.engine.begin() as connection:
            connection.execute(
                update(sessions)
                .where(sessions.c.token_hash == token_digest(token), sessions.c.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )

    def change_password(self, user_id, current_password, new_password, current_token=None):
        with self.engine.begin() as connection:
            row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
            if not row or not verify_password(current_password, row["password_hash"]):
                raise ValueError("当前密码不正确")
            connection.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(password_hash=hash_password(new_password), must_change_password=False)
            )
            revoke_query = update(sessions).where(
                sessions.c.user_id == user_id,
                sessions.c.revoked_at.is_(None),
            )
            if current_token:
                revoke_query = revoke_query.where(sessions.c.token_hash != token_digest(current_token))
            connection.execute(revoke_query.values(revoked_at=utcnow()))
            self.audit(connection, user_id, "auth.change_password", "user", str(user_id), "用户修改密码", {})

    def list_users(self, include_archived=False):
        with self.engine.connect() as connection:
            query = select(users).order_by(users.c.id)
            if not include_archived:
                query = query.where(users.c.archived_at.is_(None))
            rows = connection.execute(query).mappings().all()
            return [self.public_user(row) for row in rows]

    def user_deletion_impact(self, user_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
            if not row:
                raise ValueError("员工不存在")
            counts = {
                "audit_logs": connection.execute(select(func.count()).select_from(audit_logs).where(audit_logs.c.actor_user_id == user_id)).scalar_one(),
                "tasks": connection.execute(select(func.count()).select_from(monthly_tasks).where(monthly_tasks.c.owner_user_id == user_id)).scalar_one(),
                "batches": connection.execute(select(func.count()).select_from(import_batches).where(import_batches.c.submitted_by_user_id == user_id)).scalar_one(),
                "responsibilities": connection.execute(select(func.count()).select_from(responsibilities).where(responsibilities.c.owner_user_id == user_id)).scalar_one(),
                "uploaded_files": connection.execute(select(func.count()).select_from(raw_files).where(raw_files.c.uploaded_by_user_id == user_id)).scalar_one(),
                "write_operations": connection.execute(select(func.count()).select_from(target_write_operations).where(target_write_operations.c.created_by_user_id == user_id)).scalar_one(),
            }
            return self._json_ready({"user": self.public_user(row), "mode": "archive", "counts": counts})

    def archive_user(self, actor_id, user_id):
        if actor_id == user_id:
            raise ValueError("不能删除当前登录账号")
        with self.engine.begin() as connection:
            effective_admins = list(connection.execute(
                select(users.c.id).where(users.c.role == "admin", users.c.disabled.is_(False), users.c.archived_at.is_(None))
            ).scalars())
            row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
            if not row:
                raise ValueError("员工不存在")
            if row.get("archived_at"):
                raise ValueError("员工已经删除")
            if row["role"] == "admin" and not row["disabled"] and len(effective_admins) == 1:
                raise ValueError("不能删除最后一个有效管理员")
            archived_at = utcnow()
            connection.execute(
                update(users).where(users.c.id == user_id).values(disabled=True, archived_at=archived_at)
            )
            connection.execute(
                update(sessions).where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None)).values(revoked_at=archived_at)
            )
            cutoff_month = next_calendar_month(previous_calendar_month())
            template_ids = list(connection.execute(select(template_definitions.c.id)).scalars())
            reassigned_templates = []
            for template_id in template_ids:
                if self._owner_for_month(connection, template_id, cutoff_month) != user_id:
                    continue
                existing = connection.execute(select(responsibilities).where(
                    responsibilities.c.template_id == template_id,
                    responsibilities.c.effective_month == cutoff_month,
                )).mappings().first()
                if existing:
                    connection.execute(update(responsibilities).where(responsibilities.c.id == existing["id"]).values(owner_user_id=None, created_by_user_id=actor_id))
                else:
                    connection.execute(insert(responsibilities).values(
                        template_id=template_id, owner_user_id=None, effective_month=cutoff_month, created_by_user_id=actor_id
                    ))
                reassigned_templates.append(template_id)
            candidate_tasks = connection.execute(select(monthly_tasks).where(
                monthly_tasks.c.owner_user_id == user_id,
                monthly_tasks.c.report_month >= cutoff_month,
                monthly_tasks.c.status == "pending_submission",
                monthly_tasks.c.current_batch_id.is_(None),
            )).mappings().all()
            task_ids_with_batches = set(connection.execute(
                select(import_batches.c.task_id).where(import_batches.c.task_id.in_([item["id"] for item in candidate_tasks]))
            ).scalars()) if candidate_tasks else set()
            cleared_task_ids = [item["id"] for item in candidate_tasks if item["id"] not in task_ids_with_batches]
            if cleared_task_ids:
                connection.execute(update(monthly_tasks).where(monthly_tasks.c.id.in_(cleared_task_ids)).values(owner_user_id=None, updated_at=archived_at))
            self.audit(connection, actor_id, "users.archive", "user", str(user_id), "删除员工账号并保留历史记录", {
                "username": row["username"], "future_effective_month": cutoff_month,
                "unassigned_template_count": len(reassigned_templates), "cleared_task_count": len(cleared_task_ids),
            })
            archived = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
            return self.public_user(archived)

    def restore_user(self, actor_id, user_id):
        with self.engine.begin() as connection:
            row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
            if not row:
                raise ValueError("员工不存在")
            if not row.get("archived_at"):
                raise ValueError("员工未被删除")
            connection.execute(update(users).where(users.c.id == user_id).values(archived_at=None, disabled=True))
            self.audit(connection, actor_id, "users.restore", "user", str(user_id), "恢复已删除员工账号", {"username": row["username"]})
            restored = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
            return self.public_user(restored)

    def create_user(self, actor_id, payload):
        password = payload.get("password")
        if not password:
            raise ValueError("新增账号必须提供初始密码")
        if payload.get("role") not in {"admin", "submitter"}:
            raise ValueError("角色只能是 admin 或 submitter")
        with self.engine.begin() as connection:
            result = connection.execute(
                insert(users).values(
                    username=payload["username"],
                    display_name=payload["display_name"],
                    role=payload["role"],
                    department=payload.get("department") or "业务部门",
                    password_hash=hash_password(password),
                    must_change_password=True,
                    disabled=False,
                )
            )
            user_id = result.inserted_primary_key[0]
            self.audit(connection, actor_id, "users.create", "user", str(user_id), "新增员工账号", {"username": payload["username"]})
            row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
            return self.public_user(row)

    def update_user(self, actor_id, user_id, payload):
        allowed = {key: payload[key] for key in ("display_name", "role", "department", "disabled") if key in payload}
        if "role" in allowed and allowed["role"] not in {"admin", "submitter"}:
            raise ValueError("角色只能是 admin 或 submitter")
        with self.engine.begin() as connection:
            effective_admins_query = select(users.c.id).where(
                users.c.role == "admin", users.c.disabled.is_(False), users.c.archived_at.is_(None)
            ).order_by(users.c.id)
            if self.dialect == "mysql":
                effective_admins_query = effective_admins_query.with_for_update()
            effective_admin_ids = list(connection.execute(effective_admins_query).scalars())
            user_query = select(users).where(users.c.id == user_id)
            if self.dialect == "mysql" and user_id not in effective_admin_ids:
                user_query = user_query.with_for_update()
            current = connection.execute(user_query).mappings().first()
            if not current:
                raise ValueError("员工不存在")
            if current.get("archived_at"):
                raise ValueError("已删除员工不能编辑，请先恢复")
            resulting_role = allowed.get("role", current["role"])
            resulting_disabled = allowed.get("disabled", current["disabled"])
            removes_effective_admin = (
                current["role"] == "admin"
                and not current["disabled"]
                and (resulting_role != "admin" or resulting_disabled)
            )
            if removes_effective_admin and len(effective_admin_ids) == 1:
                raise ValueError("不能停用或降级最后一个有效管理员")
            connection.execute(update(users).where(users.c.id == user_id).values(**allowed))
            self.audit(connection, actor_id, "users.update", "user", str(user_id), "更新员工账号", allowed)
            row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
            return self.public_user(row)

    def reset_user_password(self, actor_id, user_id, new_password):
        with self.engine.begin() as connection:
            row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
            if not row:
                raise ValueError("员工不存在")
            connection.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(password_hash=hash_password(new_password), must_change_password=True)
            )
            connection.execute(
                update(sessions)
                .where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
            self.audit(connection, actor_id, "users.reset_password", "user", str(user_id), "重置员工密码", {})
            row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
            return self.public_user(row)

    def list_templates(self, include_archived=False, report_month=None):
        if report_month:
            self._validate_report_month(report_month)
            if report_month > visible_report_month_cutoff():
                return []
        scope_month = report_month or visible_report_month_cutoff()
        with self.engine.connect() as connection:
            query = select(template_definitions).order_by(template_definitions.c.sort_order)
            if not include_archived:
                query = query.where(template_definitions.c.archived_at.is_(None))
            rows = connection.execute(query).mappings().all()
            if not rows:
                return []
            template_ids = [row["id"] for row in rows]
            version_rows = connection.execute(
                select(template_versions)
                .where(template_versions.c.template_id.in_(template_ids))
                .order_by(
                    template_versions.c.template_id,
                    template_versions.c.effective_month.desc(),
                    template_versions.c.id.desc(),
                )
            ).mappings().all()
            latest_versions = {}
            for version in version_rows:
                if version["effective_month"] > scope_month:
                    continue
                latest_versions.setdefault(version["template_id"], version)
            version_ids = [version["id"] for version in latest_versions.values()]
            mapping_rows = connection.execute(
                select(template_table_mappings).where(
                    template_table_mappings.c.template_version_id.in_(version_ids),
                    template_table_mappings.c.archived_at.is_(None),
                )
            ).mappings().all() if version_ids else []
            mappings_by_version = defaultdict(list)
            for mapping in mapping_rows:
                mappings_by_version[mapping["template_version_id"]].append(mapping)
            connection_ids = {mapping["data_connection_id"] for mapping in mapping_rows}
            connection_rows = connection.execute(
                select(data_connections).where(data_connections.c.id.in_(connection_ids))
            ).mappings().all() if connection_ids else []
            connections_by_id = {item["id"]: item for item in connection_rows}
            responsibility_rows = connection.execute(
                select(responsibilities)
                .where(responsibilities.c.template_id.in_(template_ids))
                .order_by(
                    responsibilities.c.template_id,
                    responsibilities.c.effective_month.desc(),
                    responsibilities.c.id.desc(),
                )
            ).mappings().all()
            responsibilities_by_template = {}
            for responsibility in responsibility_rows:
                responsibilities_by_template.setdefault(responsibility["template_id"], []).append(responsibility)
            owner_ids = {item["owner_user_id"] for item in responsibility_rows if item["owner_user_id"]}
            owner_rows = connection.execute(select(users).where(users.c.id.in_(owner_ids))).mappings().all() if owner_ids else []
            owners_by_id = {item["id"]: self.public_user(item) for item in owner_rows}

            payloads = []
            for row in rows:
                latest = latest_versions.get(row["id"])
                payload = dict(row)
                if latest:
                    payload.update(
                        {
                            "version": latest["version"],
                            "effective_month": latest["effective_month"],
                            "sample_filename": latest["sample_filename"],
                            "match": json.loads(latest["match_json"]),
                            "header_keywords": json.loads(latest["header_keywords_json"]),
                            "date_fields": json.loads(latest["date_fields_json"]),
                            "required_fields": json.loads(latest["required_fields_json"]),
                            "numeric_fields": json.loads(latest["numeric_fields_json"]),
                            "validation_rules": json.loads(latest["validation_rules_json"] or "[]"),
                            "template_file": self._template_file_payload(latest),
                        }
                    )
                    version_mappings = sorted(
                        mappings_by_version.get(latest["id"], []),
                        key=lambda item: (not bool(item.get("is_active")), item["id"]),
                    )
                    payload["table_mappings"] = [self._mapping_payload_from_rows(mapping, latest, row, connections_by_id.get(mapping["data_connection_id"])) for mapping in version_mappings]
                    payload["table_mapping"] = next((item for item in payload["table_mappings"] if item.get("is_active")), None)
                else:
                    payload.update(describe_template(TEMPLATES[0]))
                    payload["table_mapping"] = None
                    payload["table_mappings"] = []
                sheet_names = [item.get("name") for item in ((payload.get("template_file") or {}).get("analysis") or {}).get("sheets", []) if item.get("name")]
                enabled_sheets = {item.get("source_sheet_name") for item in payload["table_mappings"] if item.get("is_active") and item.get("status") == "enabled"}
                payload["target_strategy"] = "mapped_table" if sheet_names and (set(sheet_names) <= enabled_sheets or (len(sheet_names) == 1 and any(item.get("is_active") and item.get("status") == "enabled" for item in payload["table_mappings"]))) else "unconfigured"
                effective_month = scope_month
                responsibility = next(
                    (
                        item for item in responsibilities_by_template.get(row["id"], [])
                        if item["effective_month"] <= effective_month
                    ),
                    None,
                )
                payload["owner"] = owners_by_id.get(responsibility["owner_user_id"]) if responsibility else None
                payloads.append(self._json_ready(payload))
            return payloads

    def get_template_by_code(self, code, version=None, report_month=None):
        if report_month:
            self._validate_report_month(report_month)
            if report_month > visible_report_month_cutoff():
                return None
        with self.engine.connect() as connection:
            row = connection.execute(select(template_definitions).where(template_definitions.c.code == code)).mappings().first()
            return self._template_payload(connection, row, version=version, report_month=report_month) if row else None

    def _template_version_correction_state(self, connection, version_id):
        batch_months = sorted(set(connection.execute(
            select(import_batches.c.report_month).where(import_batches.c.template_version_id == version_id)
        ).scalars()))
        task_rows = connection.execute(
            select(monthly_tasks.c.report_month, monthly_tasks.c.status, monthly_tasks.c.current_batch_id)
            .where(monthly_tasks.c.template_version_id == version_id)
        ).mappings().all()
        unsafe_task_months = sorted({
            row["report_month"] for row in task_rows
            if row["status"] != "pending_submission" or row["current_batch_id"] is not None
        })
        blocker = None
        if batch_months:
            blocker = f"模板版本已有填报批次（{', '.join(batch_months)}），不能原地修改，请创建新版本"
        elif unsafe_task_months:
            blocker = f"模板版本存在非待填任务（{', '.join(unsafe_task_months)}），不能原地修改，请创建新版本"
        return {
            "allowed": blocker is None,
            "blocker": blocker,
            "batch_months": batch_months,
            "unsafe_task_months": unsafe_task_months,
            "task_count": len(task_rows),
        }

    def _mapping_usage_months(self, connection, version_id, mapping_id):
        """Return months whose immutable operation snapshot used this mapping."""
        rows = connection.execute(
            select(import_batches.c.report_month, target_write_operations.c.table_mapping_id, target_write_operations.c.mapping_snapshot_json)
            .join(target_write_operations, target_write_operations.c.batch_id == import_batches.c.id)
            .where(import_batches.c.template_version_id == version_id)
        ).mappings().all()
        months = set()
        for row in rows:
            used = row["table_mapping_id"] == mapping_id
            if not used:
                try:
                    snapshots = json.loads(row.get("mapping_snapshot_json") or "[]")
                except (TypeError, ValueError):
                    snapshots = []
                used = any(item.get("mapping_id") == mapping_id for item in snapshots if isinstance(item, dict))
            if used:
                months.add(row["report_month"])
        return sorted(months)

    def _template_mapping_correction_state(self, connection, version_id):
        """Mapping candidates remain editable until that exact candidate is used."""
        task_count = connection.execute(
            select(func.count()).select_from(monthly_tasks).where(monthly_tasks.c.template_version_id == version_id)
        ).scalar_one()
        return {
            "allowed": True,
            "blocker": None,
            "operation_months": [],
            "task_count": task_count,
        }

    @staticmethod
    def _inherited_template_file_values(version_row):
        return {
            "template_file_original_name": version_row.get("template_file_original_name"),
            "template_file_path": version_row.get("template_file_path"),
            "template_file_sha256": version_row.get("template_file_sha256"),
            "template_file_size_bytes": version_row.get("template_file_size_bytes"),
            "template_file_uploaded_at": version_row.get("template_file_uploaded_at"),
            "template_file_analysis_json": version_row.get("template_file_analysis_json") or "{}",
        }

    def update_template(self, actor_id, code, payload):
        if payload.get("effective_month"):
            self._validate_report_month(payload["effective_month"])
        definition_keys = {key: payload[key] for key in ("name", "short_name", "description", "status") if key in payload}
        version_keys = {
            "version": payload.get("version"),
            "effective_month": payload.get("effective_month"),
            "sample_filename": payload.get("sample_filename"),
            "match_json": json.dumps(payload.get("match", []), ensure_ascii=False) if "match" in payload else None,
            "header_keywords_json": json.dumps(payload.get("header_keywords", []), ensure_ascii=False) if "header_keywords" in payload else None,
            "date_fields_json": json.dumps(payload.get("date_fields", []), ensure_ascii=False) if "date_fields" in payload else None,
            "required_fields_json": json.dumps(payload.get("required_fields", []), ensure_ascii=False) if "required_fields" in payload else None,
            "numeric_fields_json": json.dumps(payload.get("numeric_fields", []), ensure_ascii=False) if "numeric_fields" in payload else None,
            "validation_rules_json": json.dumps(payload.get("validation_rules", []), ensure_ascii=False) if "validation_rules" in payload else None,
        }
        version_keys = {key: value for key, value in version_keys.items() if value not in (None, "")}
        audit_action = "templates.update"
        audit_message = "更新模板配置"
        with self.engine.begin() as connection:
            template = connection.execute(
                select(template_definitions).where(template_definitions.c.code == code)
            ).mappings().first()
            if not template:
                raise ValueError("模板不存在")
            if template.get("archived_at"):
                raise ValueError("已删除模板不能编辑，请先恢复")
            if definition_keys:
                connection.execute(update(template_definitions).where(template_definitions.c.id == template["id"]).values(**definition_keys))
                if definition_keys.get("status") == "disabled" and template["status"] != "disabled":
                    candidate_tasks = connection.execute(select(monthly_tasks).where(
                        monthly_tasks.c.template_id == template["id"],
                        monthly_tasks.c.status == "pending_submission",
                        monthly_tasks.c.current_batch_id.is_(None),
                    )).mappings().all()
                    task_ids_with_batches = set(connection.execute(
                        select(import_batches.c.task_id).where(import_batches.c.task_id.in_([item["id"] for item in candidate_tasks]))
                    ).scalars()) if candidate_tasks else set()
                    cancellable_ids = [item["id"] for item in candidate_tasks if item["id"] not in task_ids_with_batches]
                    if cancellable_ids:
                        connection.execute(update(monthly_tasks).where(monthly_tasks.c.id.in_(cancellable_ids)).values(status="cancelled", updated_at=utcnow()))
            if version_keys:
                latest = self._version_for_month(connection, template["id"], "9999-12")
                existing_values = {}
                if latest:
                    existing_values = {
                        "template_id": template["id"],
                        "version": latest["version"],
                        "effective_month": latest["effective_month"],
                        "sample_filename": latest["sample_filename"],
                        "match_json": latest["match_json"],
                        "header_keywords_json": latest["header_keywords_json"],
                        "date_fields_json": latest["date_fields_json"],
                        "required_fields_json": latest["required_fields_json"],
                        "numeric_fields_json": latest["numeric_fields_json"],
                        "validation_rules_json": latest["validation_rules_json"],
                    }
                existing_values.update(version_keys)
                if latest:
                    tracked_keys = (
                        "version",
                        "effective_month",
                        "sample_filename",
                        "match_json",
                        "header_keywords_json",
                        "date_fields_json",
                        "required_fields_json",
                        "numeric_fields_json",
                        "validation_rules_json",
                    )
                    changed = any(existing_values[key] != latest[key] for key in tracked_keys)
                    correction_state = self._template_version_correction_state(connection, latest["id"])
                    version_is_used = correction_state["task_count"] > 0
                    if changed and existing_values["version"] == latest["version"]:
                        if correction_state["blocker"]:
                            raise ValueError(correction_state["blocker"])
                        connection.execute(update(template_versions).where(template_versions.c.id == latest["id"]).values(**existing_values))
                        connection.execute(
                            update(template_table_mappings)
                            .where(template_table_mappings.c.template_version_id == latest["id"])
                            .values(status="draft", last_validation_json="{}", last_validated_at=None, updated_at=utcnow())
                        )
                        if version_is_used:
                            audit_action = "templates.version_correct"
                            audit_message = "无批次纠正模板版本"
                    elif changed and (version_is_used or correction_state["batch_months"]):
                        if existing_values["effective_month"] <= latest["effective_month"]:
                            raise ValueError("新版本生效月份必须晚于当前版本")
                        result = connection.execute(insert(template_versions).values(
                            **existing_values,
                            **self._inherited_template_file_values(latest),
                        ))
                        previous_mappings = connection.execute(
                            select(template_table_mappings).where(
                                template_table_mappings.c.template_version_id == latest["id"],
                                template_table_mappings.c.archived_at.is_(None),
                            )
                        ).mappings().all()
                        for previous_mapping in previous_mappings:
                            connection.execute(
                                insert(template_table_mappings).values(
                                    template_version_id=result.inserted_primary_key[0],
                                    source_sheet_name=previous_mapping.get("source_sheet_name"),
                                    data_connection_id=previous_mapping["data_connection_id"],
                                    target_schema=previous_mapping["target_schema"],
                                    target_table=previous_mapping["target_table"],
                                    is_active=previous_mapping.get("is_active", True),
                                    field_mapping_json=previous_mapping.get("field_mapping_json") or "{}",
                                    status="draft",
                                    last_validation_json="{}",
                                    created_by_user_id=actor_id,
                                    updated_at=utcnow(),
                                )
                            )
                    elif changed:
                        connection.execute(update(template_versions).where(template_versions.c.id == latest["id"]).values(**existing_values))
                        connection.execute(
                            update(template_table_mappings)
                            .where(template_table_mappings.c.template_version_id == latest["id"])
                            .values(status="draft", last_validation_json="{}", last_validated_at=None, updated_at=utcnow())
                        )
                else:
                    connection.execute(insert(template_versions).values(**existing_values))
            self.audit(connection, actor_id, audit_action, "template", code, audit_message, {"code": code})
            row = connection.execute(select(template_definitions).where(template_definitions.c.code == code)).mappings().first()
            return self._template_payload(connection, row)

    def template_deletion_impact(self, code):
        with self.engine.connect() as connection:
            template = connection.execute(select(template_definitions).where(template_definitions.c.code == code)).mappings().first()
            if not template:
                raise ValueError("模板不存在")
            counts = {
                "versions": connection.execute(select(func.count()).select_from(template_versions).where(template_versions.c.template_id == template["id"])).scalar_one(),
                "mappings": connection.execute(
                    select(func.count())
                    .select_from(template_table_mappings.join(
                        template_versions,
                        template_table_mappings.c.template_version_id == template_versions.c.id,
                    ))
                    .where(template_versions.c.template_id == template["id"])
                ).scalar_one(),
                "responsibilities": connection.execute(select(func.count()).select_from(responsibilities).where(responsibilities.c.template_id == template["id"])).scalar_one(),
                "tasks": connection.execute(select(func.count()).select_from(monthly_tasks).where(monthly_tasks.c.template_id == template["id"])).scalar_one(),
                "batches": connection.execute(select(func.count()).select_from(import_batches).where(import_batches.c.template_id == template["id"])).scalar_one(),
            }
            mode = "archive" if counts["tasks"] or counts["batches"] else "delete"
            return self._json_ready({"template": self._template_payload(connection, template), "mode": mode, "counts": counts})

    def delete_template(self, actor_id, code):
        with self.engine.begin() as connection:
            template = connection.execute(select(template_definitions).where(template_definitions.c.code == code)).mappings().first()
            if not template:
                raise ValueError("模板不存在")
            if template["status"] != "disabled":
                raise ValueError("请先停用模板，再执行删除")
            task_count = connection.execute(select(func.count()).select_from(monthly_tasks).where(monthly_tasks.c.template_id == template["id"])).scalar_one()
            batch_count = connection.execute(select(func.count()).select_from(import_batches).where(import_batches.c.template_id == template["id"])).scalar_one()
            if task_count or batch_count:
                if template.get("archived_at"):
                    raise ValueError("模板已经删除")
                archived_at = utcnow()
                connection.execute(update(template_definitions).where(template_definitions.c.id == template["id"]).values(archived_at=archived_at, status="disabled"))
                self.audit(connection, actor_id, "templates.archive", "template", code, "归档删除模板并保留历史记录", {"task_count": task_count, "batch_count": batch_count})
                return {"code": code, "mode": "archive", "archived_at": archived_at}
            version_ids = list(connection.execute(select(template_versions.c.id).where(template_versions.c.template_id == template["id"])).scalars())
            if version_ids:
                connection.execute(delete(template_table_mappings).where(template_table_mappings.c.template_version_id.in_(version_ids)))
            connection.execute(delete(responsibilities).where(responsibilities.c.template_id == template["id"]))
            connection.execute(delete(template_versions).where(template_versions.c.template_id == template["id"]))
            self.audit(connection, actor_id, "templates.delete", "template", code, "删除未使用模板", {"task_count": 0, "batch_count": 0})
            connection.execute(delete(template_definitions).where(template_definitions.c.id == template["id"]))
            return {"code": code, "mode": "delete", "archived_at": None}

    def restore_template(self, actor_id, code):
        with self.engine.begin() as connection:
            template = connection.execute(select(template_definitions).where(template_definitions.c.code == code)).mappings().first()
            if not template:
                raise ValueError("模板不存在")
            if not template.get("archived_at"):
                raise ValueError("模板未被归档")
            connection.execute(update(template_definitions).where(template_definitions.c.id == template["id"]).values(archived_at=None, status="disabled"))
            self.audit(connection, actor_id, "templates.restore", "template", code, "恢复归档模板", {})
            restored = connection.execute(select(template_definitions).where(template_definitions.c.id == template["id"])).mappings().first()
            return self._template_payload(connection, restored)

    def create_template(self, actor_id, payload):
        code = payload["code"]
        self._validate_report_month(payload.get("effective_month") or "2026-08")
        with self.engine.begin() as connection:
            exists = connection.execute(select(template_definitions.c.id).where(template_definitions.c.code == code)).first()
            if exists:
                raise ValueError("模板编码已存在")
            sort_order = connection.execute(select(func.max(template_definitions.c.sort_order))).scalar() or 100
            result = connection.execute(
                insert(template_definitions).values(
                    code=code,
                    name=payload["name"],
                    short_name=payload.get("short_name") or payload["name"],
                    description=payload.get("description") or "",
                    status=payload.get("status") or "draft",
                    sort_order=sort_order + 10,
                )
            )
            template_id = result.inserted_primary_key[0]
            connection.execute(
                insert(template_versions).values(
                    template_id=template_id,
                    version=payload.get("version") or "1.0",
                    effective_month=payload.get("effective_month") or "2026-08",
                    sample_filename=payload.get("sample_filename") or "",
                    match_json=json.dumps(payload.get("match", []), ensure_ascii=False),
                    header_keywords_json=json.dumps(payload.get("header_keywords", []), ensure_ascii=False),
                    date_fields_json=json.dumps(payload.get("date_fields", []), ensure_ascii=False),
                    required_fields_json=json.dumps(payload.get("required_fields", []), ensure_ascii=False),
                    numeric_fields_json=json.dumps(payload.get("numeric_fields", []), ensure_ascii=False),
                    validation_rules_json=json.dumps(payload.get("validation_rules", []), ensure_ascii=False),
                )
            )
            self.audit(connection, actor_id, "templates.create", "template", code, "新增模板草稿", {"code": code})
            row = connection.execute(select(template_definitions).where(template_definitions.c.id == template_id)).mappings().first()
            return self._template_payload(connection, row)

    def create_template_version(self, actor_id, code, version, effective_month):
        self._validate_report_month(effective_month)
        with self.engine.begin() as connection:
            template = connection.execute(
                select(template_definitions).where(template_definitions.c.code == code)
            ).mappings().first()
            if not template:
                raise ValueError("模板不存在")
            if template.get("archived_at"):
                raise ValueError("已删除模板不能创建新版本，请先恢复")
            latest = connection.execute(
                select(template_versions)
                .where(template_versions.c.template_id == template["id"])
                .order_by(template_versions.c.effective_month.desc(), template_versions.c.id.desc())
                .limit(1)
            ).mappings().first()
            if not latest:
                raise ValueError("模板当前版本不存在")
            if connection.execute(
                select(template_versions.c.id).where(
                    template_versions.c.template_id == template["id"], template_versions.c.version == version
                )
            ).first():
                raise ValueError("模板版本已存在")
            if effective_month <= latest["effective_month"]:
                raise ValueError("新版本生效月份必须晚于当前版本")
            values = {
                "template_id": template["id"],
                "version": version,
                "effective_month": effective_month,
                "sample_filename": latest["sample_filename"],
                "match_json": latest["match_json"],
                "header_keywords_json": latest["header_keywords_json"],
                "date_fields_json": latest["date_fields_json"],
                "required_fields_json": latest["required_fields_json"],
                "numeric_fields_json": latest["numeric_fields_json"],
                "validation_rules_json": latest["validation_rules_json"],
                **self._inherited_template_file_values(latest),
            }
            result = connection.execute(insert(template_versions).values(**values))
            previous_mappings = connection.execute(
                select(template_table_mappings).where(
                    template_table_mappings.c.template_version_id == latest["id"],
                    template_table_mappings.c.archived_at.is_(None),
                )
            ).mappings().all()
            for previous_mapping in previous_mappings:
                connection.execute(
                    insert(template_table_mappings).values(
                        template_version_id=result.inserted_primary_key[0],
                        source_sheet_name=previous_mapping.get("source_sheet_name"),
                        data_connection_id=previous_mapping["data_connection_id"],
                        target_schema=previous_mapping["target_schema"],
                        target_table=previous_mapping["target_table"],
                        is_active=previous_mapping.get("is_active", True),
                        field_mapping_json=previous_mapping.get("field_mapping_json") or "{}",
                        status="draft",
                        last_validation_json="{}",
                        created_by_user_id=actor_id,
                        updated_at=utcnow(),
                    )
                )
            self.audit(connection, actor_id, "templates.version_create", "template", code, "创建模板新版本", {"version": version, "effective_month": effective_month})
            row = connection.execute(select(template_definitions).where(template_definitions.c.id == template["id"])).mappings().first()
            return self._template_payload(connection, row)

    def attach_template_file(self, actor_id, code, version, payload):
        with self.engine.begin() as connection:
            row = connection.execute(
                select(template_versions)
                .join(template_definitions, template_definitions.c.id == template_versions.c.template_id)
                .where(template_definitions.c.code == code, template_versions.c.version == version)
            ).mappings().first()
            if not row:
                raise ValueError("模板版本不存在")
            replacing = bool(row["template_file_path"])
            correction_state = self._template_version_correction_state(connection, row["id"])
            if correction_state["blocker"]:
                raise ValueError(correction_state["blocker"])
            connection.execute(
                update(template_versions)
                .where(template_versions.c.id == row["id"])
                .values(
                    template_file_original_name=payload["original_name"],
                    template_file_path=str(payload["path"]),
                    template_file_sha256=payload["sha256"],
                    template_file_size_bytes=payload["size_bytes"],
                    template_file_uploaded_at=utcnow(),
                    template_file_analysis_json=json.dumps(payload["analysis"], ensure_ascii=False),
                )
            )
            connection.execute(
                update(template_table_mappings)
                .where(template_table_mappings.c.template_version_id == row["id"])
                .values(
                    status="draft",
                    last_validation_json="{}",
                    last_validated_at=None,
                    updated_at=utcnow(),
                )
            )
            self.audit(
                connection,
                actor_id,
                "templates.version_correct" if correction_state["task_count"] else ("templates.file_replace" if replacing else "templates.file_upload"),
                "template",
                code,
                "无批次纠正模板文件" if correction_state["task_count"] else ("替换模板文件" if replacing else "上传模板文件"),
                {"version": version, "sha256": payload["sha256"], "correction": bool(correction_state["task_count"])},
            )
            template = connection.execute(select(template_definitions).where(template_definitions.c.code == code)).mappings().first()
            return self._template_payload(connection, template, version=version)

    def get_template_file_record(self, code, version=None):
        with self.engine.connect() as connection:
            query = (
                select(template_versions)
                .join(template_definitions, template_definitions.c.id == template_versions.c.template_id)
                .where(template_definitions.c.code == code)
            )
            if version:
                query = query.where(template_versions.c.version == version)
            else:
                query = query.order_by(template_versions.c.effective_month.desc(), template_versions.c.id.desc()).limit(1)
            row = connection.execute(query).mappings().first()
            return dict(row) if row else None

    def update_template_file_analysis(self, actor_id, code, version, analysis):
        with self.engine.begin() as connection:
            row = connection.execute(
                select(template_versions)
                .join(template_definitions, template_definitions.c.id == template_versions.c.template_id)
                .where(template_definitions.c.code == code, template_versions.c.version == version)
            ).mappings().first()
            if not row or not row["template_file_path"]:
                raise ValueError("模板文件未上传")
            correction_state = self._template_version_correction_state(connection, row["id"])
            if correction_state["blocker"]:
                raise ValueError(correction_state["blocker"])
            connection.execute(
                update(template_versions)
                .where(template_versions.c.id == row["id"])
                .values(template_file_analysis_json=json.dumps(analysis, ensure_ascii=False))
            )
            connection.execute(
                update(template_table_mappings)
                .where(template_table_mappings.c.template_version_id == row["id"])
                .values(status="draft", last_validation_json="{}", last_validated_at=None, updated_at=utcnow())
            )
            self.audit(
                connection,
                actor_id,
                "templates.version_correct" if correction_state["task_count"] else "templates.file_header_confirm",
                "template",
                code,
                "无批次纠正模板表头" if correction_state["task_count"] else "确认模板文件表头",
                {"version": version, "correction": bool(correction_state["task_count"])},
            )
            template = connection.execute(select(template_definitions).where(template_definitions.c.code == code)).mappings().first()
            return self._template_payload(connection, template, version=version)

    def get_template_version(self, template_code, report_month):
        if report_month and report_month > visible_report_month_cutoff():
            return None
        with self.engine.connect() as connection:
            template = connection.execute(
                select(template_definitions).where(template_definitions.c.code == template_code)
            ).mappings().first()
            if not template:
                return None
            version = self._version_for_month(connection, template["id"], report_month or "9999-12")
            if not version:
                return None
            return dict(version)

    def list_responsibilities(self, report_month=None):
        if report_month:
            self._validate_report_month(report_month)
            if report_month > visible_report_month_cutoff():
                return []
        with self.engine.connect() as connection:
            query = (
                select(responsibilities, template_definitions.c.code, template_definitions.c.short_name)
                .join(template_definitions, responsibilities.c.template_id == template_definitions.c.id)
                .where(template_definitions.c.archived_at.is_(None))
                .order_by(
                    template_definitions.c.sort_order,
                    responsibilities.c.effective_month.desc(),
                    responsibilities.c.id.desc(),
                )
            )
            if report_month:
                query = query.where(responsibilities.c.effective_month <= report_month)
            rows = connection.execute(query).mappings().all()
            if report_month:
                scoped_rows = {}
                for row in rows:
                    scoped_rows.setdefault(row["template_id"], row)
                rows = list(scoped_rows.values())
            owner_ids = {row["owner_user_id"] for row in rows if row["owner_user_id"]}
            owner_rows = connection.execute(select(users).where(users.c.id.in_(owner_ids))).mappings().all() if owner_ids else []
            owners_by_id = {row["id"]: self.public_user(row) for row in owner_rows}
            return [
                self._json_ready(
                    {
                        "id": row["id"],
                        "template": {"code": row["code"], "short_name": row["short_name"]},
                        "owner": owners_by_id.get(row["owner_user_id"]),
                        "effective_month": row["effective_month"],
                        "created_at": row["created_at"],
                    }
                )
                for row in rows
            ]

    def set_responsibility(self, actor_id, template_code, owner_user_id, effective_month):
        self._validate_report_month(effective_month)
        with self.engine.begin() as connection:
            template = connection.execute(
                select(template_definitions).where(template_definitions.c.code == template_code)
            ).mappings().first()
            if not template:
                raise ValueError("模板不存在")
            if owner_user_id is None:
                raise ValueError("必须选择负责人")
            owner = connection.execute(
                select(users).where(users.c.id == owner_user_id, users.c.role == "submitter", users.c.disabled.is_(False))
            ).mappings().first()
            if not owner:
                raise ValueError("负责人不存在、已停用或不是填报人")
            unresolved_query = (
                select(responsibilities)
                .where(
                    responsibilities.c.template_id == template["id"],
                    responsibilities.c.owner_user_id.is_(None),
                )
                .order_by(responsibilities.c.effective_month, responsibilities.c.id)
                .limit(1)
            )
            if self.dialect == "mysql":
                unresolved_query = unresolved_query.with_for_update()
            unresolved = connection.execute(unresolved_query).mappings().first()
            if unresolved:
                if effective_month != unresolved["effective_month"]:
                    raise ValueError(f"该模板存在待配置记录，请补齐 {unresolved['effective_month']} 的负责人")
                next_responsibility = connection.execute(
                    select(responsibilities)
                    .where(
                        responsibilities.c.template_id == template["id"],
                        responsibilities.c.effective_month > unresolved["effective_month"],
                    )
                    .order_by(responsibilities.c.effective_month, responsibilities.c.id)
                    .limit(1)
                ).mappings().first()
                task_conditions = [
                    monthly_tasks.c.template_id == template["id"],
                    monthly_tasks.c.report_month >= unresolved["effective_month"],
                ]
                batch_conditions = [
                    import_batches.c.template_id == template["id"],
                    import_batches.c.report_month >= unresolved["effective_month"],
                ]
                if next_responsibility:
                    task_conditions.append(monthly_tasks.c.report_month < next_responsibility["effective_month"])
                    batch_conditions.append(import_batches.c.report_month < next_responsibility["effective_month"])
                task_query = select(monthly_tasks).where(and_(*task_conditions)).order_by(monthly_tasks.c.report_month)
                if self.dialect == "mysql":
                    task_query = task_query.with_for_update()
                affected_tasks = connection.execute(task_query).mappings().all()
                batch_count = connection.execute(
                    select(func.count()).select_from(import_batches).where(and_(*batch_conditions))
                ).scalar_one()
                unsafe_tasks = [
                    task for task in affected_tasks
                    if task["owner_user_id"] is not None
                    or task["status"] != "pending_submission"
                    or task["current_batch_id"] is not None
                ]
                if batch_count or unsafe_tasks:
                    raise ValueError("待配置月份已产生上传批次或处理记录，不能补写负责人")
                connection.execute(
                    update(responsibilities)
                    .where(responsibilities.c.id == unresolved["id"])
                    .values(owner_user_id=owner_user_id, created_by_user_id=actor_id)
                )
                if affected_tasks:
                    connection.execute(
                        update(monthly_tasks)
                        .where(monthly_tasks.c.id.in_([task["id"] for task in affected_tasks]))
                        .values(owner_user_id=owner_user_id, updated_at=utcnow())
                    )

                collapsed_id = None
                if next_responsibility and next_responsibility["owner_user_id"] == owner_user_id:
                    following = connection.execute(
                        select(responsibilities.c.effective_month)
                        .where(
                            responsibilities.c.template_id == template["id"],
                            responsibilities.c.effective_month > next_responsibility["effective_month"],
                        )
                        .order_by(responsibilities.c.effective_month, responsibilities.c.id)
                        .limit(1)
                    ).first()
                    redundant_task_conditions = [
                        monthly_tasks.c.template_id == template["id"],
                        monthly_tasks.c.report_month >= next_responsibility["effective_month"],
                    ]
                    redundant_batch_conditions = [
                        import_batches.c.template_id == template["id"],
                        import_batches.c.report_month >= next_responsibility["effective_month"],
                    ]
                    if following:
                        redundant_task_conditions.append(monthly_tasks.c.report_month < following[0])
                        redundant_batch_conditions.append(import_batches.c.report_month < following[0])
                    redundant_tasks = connection.execute(
                        select(monthly_tasks).where(and_(*redundant_task_conditions))
                    ).mappings().all()
                    redundant_batch_count = connection.execute(
                        select(func.count()).select_from(import_batches).where(and_(*redundant_batch_conditions))
                    ).scalar_one()
                    redundant_tasks_are_safe = all(
                        task["owner_user_id"] == owner_user_id
                        and task["status"] == "pending_submission"
                        and task["current_batch_id"] is None
                        for task in redundant_tasks
                    )
                    if not redundant_batch_count and redundant_tasks_are_safe:
                        connection.execute(delete(responsibilities).where(responsibilities.c.id == next_responsibility["id"]))
                        collapsed_id = next_responsibility["id"]
                self.audit(
                    connection,
                    actor_id,
                    "responsibilities.fill_unassigned",
                    "responsibility",
                    str(unresolved["id"]),
                    "补齐待配置负责人",
                    {
                        "template_code": template_code,
                        "effective_month": unresolved["effective_month"],
                        "owner_user_id": owner_user_id,
                        "updated_task_count": len(affected_tasks),
                        "collapsed_responsibility_id": collapsed_id,
                    },
                )
            else:
                existing_query = select(responsibilities).where(
                        responsibilities.c.template_id == template["id"],
                        responsibilities.c.effective_month == effective_month,
                    )
                if self.dialect == "mysql":
                    existing_query = existing_query.with_for_update()
                existing = connection.execute(existing_query).mappings().first()
                if existing:
                    next_responsibility = connection.execute(
                        select(responsibilities.c.effective_month)
                        .where(
                            responsibilities.c.template_id == template["id"],
                            responsibilities.c.effective_month > effective_month,
                        )
                        .order_by(responsibilities.c.effective_month, responsibilities.c.id)
                        .limit(1)
                    ).first()
                    safe_task_conditions = [
                        monthly_tasks.c.template_id == template["id"],
                        monthly_tasks.c.report_month >= effective_month,
                        monthly_tasks.c.status == "pending_submission",
                        monthly_tasks.c.current_batch_id.is_(None),
                    ]
                    if next_responsibility:
                        safe_task_conditions.append(monthly_tasks.c.report_month < next_responsibility[0])
                    safe_task_ids = list(connection.execute(
                        select(monthly_tasks.c.id).where(and_(*safe_task_conditions))
                    ).scalars())
                    connection.execute(
                        update(responsibilities)
                        .where(responsibilities.c.id == existing["id"])
                        .values(owner_user_id=owner_user_id, created_by_user_id=actor_id)
                    )
                    if safe_task_ids:
                        connection.execute(
                            update(monthly_tasks)
                            .where(monthly_tasks.c.id.in_(safe_task_ids))
                            .values(owner_user_id=owner_user_id, updated_at=utcnow())
                        )
                    self.audit(
                        connection,
                        actor_id,
                        "responsibilities.edit",
                        "responsibility",
                        str(existing["id"]),
                        "编辑责任配置",
                        {
                            "template_code": template_code,
                            "effective_month": effective_month,
                            "previous_owner_user_id": existing["owner_user_id"],
                            "owner_user_id": owner_user_id,
                            "updated_task_count": len(safe_task_ids),
                        },
                    )
                else:
                    latest_task_month = connection.execute(
                        select(func.max(monthly_tasks.c.report_month)).where(monthly_tasks.c.template_id == template["id"])
                    ).scalar_one_or_none()
                    latest_batch_month = connection.execute(
                        select(func.max(import_batches.c.report_month)).where(import_batches.c.template_id == template["id"])
                    ).scalar_one_or_none()
                    protected_through = max(month for month in (latest_task_month, latest_batch_month) if month) if any((latest_task_month, latest_batch_month)) else None
                    if protected_through and effective_month <= protected_through:
                        raise ValueError(f"已有任务或批次的历史月份不可覆盖，请选择 {protected_through} 之后的月份")
                    values = {
                        "template_id": template["id"],
                        "owner_user_id": owner_user_id,
                        "effective_month": effective_month,
                        "created_by_user_id": actor_id,
                    }
                    result = connection.execute(insert(responsibilities).values(**values))
                    responsibility_id = result.inserted_primary_key[0]
                    self.audit(
                        connection,
                        actor_id,
                        "responsibilities.set",
                        "responsibility",
                        str(responsibility_id),
                        "调整负责人",
                        {"template_code": template_code, "effective_month": effective_month, "owner_user_id": owner_user_id},
                    )
                    self._generate_tasks(connection, effective_month)
        return self.list_responsibilities()

    def responsibility_deletion_impact(self, responsibility_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(responsibilities).where(responsibilities.c.id == responsibility_id)).mappings().first()
            if not row:
                raise ValueError("责任配置不存在")
            next_month = connection.execute(
                select(responsibilities.c.effective_month).where(
                    responsibilities.c.template_id == row["template_id"],
                    responsibilities.c.effective_month > row["effective_month"],
                ).order_by(responsibilities.c.effective_month).limit(1)
            ).scalar_one_or_none()
            task_conditions = [monthly_tasks.c.template_id == row["template_id"], monthly_tasks.c.report_month >= row["effective_month"]]
            batch_conditions = [import_batches.c.template_id == row["template_id"], import_batches.c.report_month >= row["effective_month"]]
            if next_month:
                task_conditions.append(monthly_tasks.c.report_month < next_month)
                batch_conditions.append(import_batches.c.report_month < next_month)
            task_count = connection.execute(select(func.count()).select_from(monthly_tasks).where(and_(*task_conditions))).scalar_one()
            batch_count = connection.execute(select(func.count()).select_from(import_batches).where(and_(*batch_conditions))).scalar_one()
            return {"id": responsibility_id, "can_delete": task_count == 0 and batch_count == 0, "task_count": task_count, "batch_count": batch_count}

    def delete_responsibility(self, actor_id, responsibility_id):
        impact = self.responsibility_deletion_impact(responsibility_id)
        if not impact["can_delete"]:
            raise ValueError("该责任配置已影响任务或批次，不能删除历史责任记录")
        with self.engine.begin() as connection:
            row = connection.execute(select(responsibilities).where(responsibilities.c.id == responsibility_id)).mappings().first()
            if not row:
                raise ValueError("责任配置不存在")
            connection.execute(delete(responsibilities).where(responsibilities.c.id == responsibility_id))
            self.audit(connection, actor_id, "responsibilities.delete", "responsibility", str(responsibility_id), "删除未生效责任配置", {"effective_month": row["effective_month"]})
        return {"id": responsibility_id, "deleted": True}

    def list_tasks(self, current_user, report_month=None):
        cutoff_month = visible_report_month_cutoff()
        if report_month:
            self._validate_report_month(report_month)
            if report_month > cutoff_month:
                return []
        with self.engine.connect() as connection:
            query = (
                select(
                    monthly_tasks,
                    template_definitions.c.code,
                    template_definitions.c.name,
                    template_definitions.c.short_name,
                    template_definitions.c.description,
                    template_definitions.c.sort_order,
                )
                .join(template_definitions, monthly_tasks.c.template_id == template_definitions.c.id)
                .order_by(template_definitions.c.sort_order)
            )
            conditions = [template_definitions.c.archived_at.is_(None)]
            if report_month:
                conditions.append(monthly_tasks.c.report_month == report_month)
            else:
                conditions.append(monthly_tasks.c.report_month <= cutoff_month)
            if current_user["role"] != "admin":
                conditions.append(monthly_tasks.c.owner_user_id == current_user["id"])
            if conditions:
                query = query.where(and_(*conditions))
            rows = connection.execute(query).mappings().all()
            if not rows:
                return []

            owner_ids = {row["owner_user_id"] for row in rows if row["owner_user_id"]}
            owners = {
                row["id"]: self.public_user(row)
                for row in connection.execute(select(users).where(users.c.id.in_(owner_ids))).mappings().all()
            } if owner_ids else {}
            version_ids = {row["template_version_id"] for row in rows}
            versions = dict(connection.execute(
                select(template_versions.c.id, template_versions.c.version).where(template_versions.c.id.in_(version_ids))
            ).all())
            batch_ids = {row["current_batch_id"] for row in rows if row["current_batch_id"]}
            batches = {
                row["id"]: row
                for row in connection.execute(select(import_batches).where(import_batches.c.id.in_(batch_ids))).mappings().all()
            } if batch_ids else {}
            months = {row["report_month"] for row in rows}
            periods = {
                row["report_month"]: row
                for row in connection.execute(select(reporting_periods).where(reporting_periods.c.report_month.in_(months))).mappings().all()
            }
            now = utcnow()
            return [self._json_ready({
                "id": row["id"],
                "report_month": row["report_month"],
                "status": row["status"],
                "access": self._task_access_from_period(row, periods.get(row["report_month"]), now=now),
                "owner": owners.get(row["owner_user_id"]),
                "template": {
                    "code": row["code"],
                    "name": row["name"],
                    "short_name": row["short_name"],
                    "description": row["description"],
                    "version": versions[row["template_version_id"]],
                },
                "current_batch": self._batch_summary(connection, batches.get(row["current_batch_id"])),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }) for row in rows]

    def _period_payload(self, connection, report_month, period=None, task_rows=None):
        period = period or self._period_row(connection, report_month)
        task_rows = task_rows if task_rows is not None else connection.execute(
            select(monthly_tasks).where(monthly_tasks.c.report_month == report_month)
        ).mappings().all()
        now = utcnow()
        reopened = [row for row in task_rows if row.get("reopened_until") and row["reopened_until"] > now]
        if not period or period["status"] == "draft":
            effective_state = "draft"
            reason = "该月份任务尚未下发"
        elif reopened and (period["status"] == "closed" or not period["closes_at"] or period["closes_at"] <= now):
            effective_state = "reopened"
            reason = "部分模板正在补报"
        elif period["status"] == "closed" or period["closed_at"] or not period["closes_at"] or period["closes_at"] <= now:
            effective_state = "closed"
            reason = "该月份已封板"
        else:
            effective_state = "open"
            reason = "任务填报中"
        return self._json_ready({
            "report_month": report_month,
            "status": period["status"] if period else "draft",
            "effective_state": effective_state,
            "reason": reason,
            "issued_at": utc_iso(period["issued_at"]) if period else None,
            "closes_at": utc_iso(period["closes_at"]) if period else None,
            "closed_at": utc_iso(period["closed_at"]) if period else None,
            "task_count": len(task_rows),
            "reopened_task_count": len(reopened),
        })

    def get_reporting_period(self, report_month):
        with self.engine.connect() as connection:
            return self._period_payload(connection, report_month)

    def list_reporting_periods(self):
        with self.engine.connect() as connection:
            cutoff_month = visible_report_month_cutoff()
            months = set(connection.execute(select(monthly_tasks.c.report_month).distinct()).scalars())
            months.update(connection.execute(select(reporting_periods.c.report_month)).scalars())
            months.add(previous_calendar_month())
            months = {month for month in months if month <= cutoff_month}
            return [self._period_payload(connection, month) for month in sorted(months, reverse=True)]

    def get_reporting_context(self, current_user):
        suggested = previous_calendar_month()
        cutoff_month = visible_report_month_cutoff()
        with self.engine.connect() as connection:
            task_query = select(monthly_tasks).where(monthly_tasks.c.report_month <= cutoff_month)
            if current_user["role"] != "admin":
                task_query = task_query.where(monthly_tasks.c.owner_user_id == current_user["id"])
            task_rows = connection.execute(task_query).mappings().all()
            by_month = {}
            for row in task_rows:
                by_month.setdefault(row["report_month"], []).append(row)
            months = set(by_month)
            months.add(suggested)
            periods = {
                row["report_month"]: row
                for row in connection.execute(select(reporting_periods).where(reporting_periods.c.report_month.in_(months))).mappings().all()
            }
            payloads = []
            now = utcnow()
            for month in sorted(months, reverse=True):
                period_payload = self._period_payload(
                    connection,
                    month,
                    period=periods.get(month),
                    task_rows=by_month.get(month, []),
                )
                visible_tasks = by_month.get(month, [])
                writable = any(
                    self._task_access_from_period(task, periods.get(month), now=now)["writable"]
                    for task in visible_tasks
                )
                period_payload["writable"] = writable
                payloads.append(period_payload)
            return {"suggested_month": suggested, "months": payloads}

    def list_task_months(self, current_user):
        with self.engine.connect() as connection:
            query = (
                select(monthly_tasks.c.report_month)
                .where(monthly_tasks.c.report_month <= visible_report_month_cutoff())
                .distinct()
                .order_by(monthly_tasks.c.report_month.desc())
            )
            if current_user["role"] != "admin":
                query = query.where(monthly_tasks.c.owner_user_id == current_user["id"])
            return list(connection.execute(query).scalars())

    def require_task_owner(self, actor_id, template_code, report_month, connection=None):
        return self.require_task_write_access(
            {"id": actor_id, "role": "submitter"}, template_code, report_month, connection=connection
        )

    def get_task(self, current_user, task_id):
        with self.engine.connect() as connection:
            row = connection.execute(
                select(
                    monthly_tasks,
                    template_definitions.c.code,
                    template_definitions.c.name,
                    template_definitions.c.short_name,
                    template_definitions.c.description,
                    template_definitions.c.sort_order,
                )
                .join(template_definitions, monthly_tasks.c.template_id == template_definitions.c.id)
                .where(monthly_tasks.c.id == task_id)
            ).mappings().first()
            if not row:
                return None
            if current_user["role"] != "admin" and row["owner_user_id"] != current_user["id"]:
                return None
            return self._task_payload(connection, row)

    def find_task_for_template_month(self, connection, template_id, report_month):
        task = connection.execute(
            select(monthly_tasks).where(
                monthly_tasks.c.template_id == template_id,
                monthly_tasks.c.report_month == report_month,
            )
        ).mappings().first()
        if task:
            return task
        version = self._version_for_month(connection, template_id, report_month)
        result = connection.execute(
            insert(monthly_tasks).values(
                template_id=template_id,
                template_version_id=version["id"],
                report_month=report_month,
                owner_user_id=self._owner_for_month(connection, template_id, report_month),
                status="pending_submission",
                updated_at=utcnow(),
            )
        )
        return connection.execute(select(monthly_tasks).where(monthly_tasks.c.id == result.inserted_primary_key[0])).mappings().first()

    def create_raw_file(self, connection, filename, stored_path, sha256, size_bytes, uploaded_by_user_id, metadata_payload):
        result = connection.execute(
            insert(raw_files).values(
                original_filename=filename,
                stored_path=str(stored_path),
                sha256=sha256,
                size_bytes=size_bytes,
                uploaded_by_user_id=uploaded_by_user_id,
                metadata_json=json.dumps(metadata_payload or {}, ensure_ascii=False),
            )
        )
        return result.inserted_primary_key[0]

    def create_import_batch(self, actor_id, actor_role, template_code, report_month, raw_file, summary, errors, records):
        with self.engine.begin() as connection:
            template = connection.execute(
                select(template_definitions).where(template_definitions.c.code == template_code)
            ).mappings().first()
            if not template:
                raise ValueError("模板不存在")
            version = self._version_for_month(connection, template["id"], report_month or "9999-12")
            if not version:
                raise ValueError("模板版本不存在")

            if report_month:
                self.require_task_write_access(
                    {"id": actor_id, "role": actor_role}, template_code, report_month, connection=connection
                )

            task = self.find_task_for_template_month(connection, template["id"], report_month) if report_month else None
            blocking_errors = sum(1 for error in errors if error.get("blocking"))
            status = "needs_changes" if blocking_errors else "pending_commit"
            summary = {**summary, "blocking_errors": blocking_errors, "warning_errors": len(errors) - blocking_errors}
            raw_file_id = self.create_raw_file(
                connection,
                raw_file["filename"],
                raw_file["stored_path"],
                raw_file["sha256"],
                raw_file["size_bytes"],
                actor_id,
                raw_file.get("metadata", {}),
            )
            result = connection.execute(
                insert(import_batches).values(
                    template_id=template["id"],
                    template_version_id=version["id"],
                    task_id=task["id"] if task else None,
                    raw_file_id=raw_file_id,
                    report_month=report_month,
                    status=status,
                    submitted_by_user_id=actor_id,
                    file_sha256=raw_file["sha256"],
                    summary_json=json.dumps(summary, ensure_ascii=False),
                )
            )
            batch_id = result.inserted_primary_key[0]
            if task and task["current_batch_id"]:
                previous_pending = connection.execute(
                    select(import_batches).where(
                        import_batches.c.id == task["current_batch_id"],
                        import_batches.c.status == "pending_commit",
                    )
                ).mappings().first()
                if previous_pending:
                    connection.execute(
                        update(import_batches)
                        .where(import_batches.c.id == previous_pending["id"])
                        .values(status="superseded")
                    )
            self._insert_errors(connection, batch_id, errors)
            if records and not blocking_errors:
                self._insert_staging(connection, batch_id, records)
            if task:
                connection.execute(
                    update(monthly_tasks)
                    .where(monthly_tasks.c.id == task["id"])
                    .values(status=status, current_batch_id=batch_id, updated_at=utcnow())
                )
            self.audit(
                connection,
                actor_id,
                "imports.validate",
                "import_batch",
                str(batch_id),
                "上传并校验文件",
                {"template_code": template_code, "report_month": report_month, "summary": summary},
            )
            row = connection.execute(select(import_batches).where(import_batches.c.id == batch_id)).mappings().first()
            return self._batch_payload(connection, row)

    def commit_batch(self, actor_id, batch_id, report_month=None):
        operation_id = None
        with self.engine.begin() as connection:
            batch_query = select(import_batches).where(import_batches.c.id == batch_id)
            if self.dialect == "mysql":
                batch_query = batch_query.with_for_update()
            batch = connection.execute(batch_query).mappings().first()
            if not batch:
                raise ValueError("批次不存在")
            if report_month is not None and report_month != batch["report_month"]:
                raise ValueError("所选期间与批次期间不一致，请刷新页面后重试")
            existing_operation = connection.execute(
                select(target_write_operations).where(
                    target_write_operations.c.batch_id == batch_id,
                    target_write_operations.c.operation_type == "commit",
                    target_write_operations.c.state != "finalized",
                )
            ).mappings().first()
            if existing_operation:
                operation_id = existing_operation["id"]
            elif batch["status"] != "pending_commit":
                raise ValueError("只有待入库记录可以确认入库")
            if not batch["report_month"] or not batch["task_id"]:
                raise ValueError("批次没有有效期间，不能入库")

            task_query = select(monthly_tasks).where(monthly_tasks.c.id == batch["task_id"])
            if self.dialect == "mysql":
                task_query = task_query.with_for_update()
            task = connection.execute(task_query).mappings().first()
            if not task or task["report_month"] != batch["report_month"]:
                raise ValueError("月度任务与批次期间不一致")
            self._ensure_task_writable(connection, task)

            staged = connection.execute(
                select(staging_records).where(staging_records.c.import_batch_id == batch_id).order_by(staging_records.c.id)
            ).mappings().all()
            if not staged:
                raise ValueError("没有可入库明细")
            template = connection.execute(
                select(template_definitions).where(template_definitions.c.id == batch["template_id"])
            ).mappings().first()
            previous = connection.execute(
                select(import_batches)
                .where(
                    import_batches.c.template_id == batch["template_id"],
                    import_batches.c.report_month == batch["report_month"],
                    import_batches.c.status == "committed",
                    import_batches.c.active_commit_key.is_not(None),
                    import_batches.c.id != batch_id,
                )
                .limit(1)
            ).mappings().first()
            mappings = connection.execute(
                select(template_table_mappings).where(
                    template_table_mappings.c.template_version_id == batch["template_version_id"],
                    template_table_mappings.c.status == "enabled",
                    template_table_mappings.c.is_active.is_(True),
                    template_table_mappings.c.archived_at.is_(None),
                )
            ).mappings().all()
            if operation_id is None and not mappings:
                raise ValueError("当前模板版本未配置有效的目标表映射，不能确认入库")
            if operation_id is None:
                readiness = self._template_version_commit_readiness(
                    connection, batch["template_version_id"], live_validate=True
                )
                if not readiness["ready"]:
                    raise ValueError("；".join(readiness["blockers"]))
                mapping_by_id = {item["id"]: item for item in mappings}
                snapshots = []
                for target in readiness.get("targets") or []:
                    item = mapping_by_id[target["mapping_id"]]
                    snapshots.append({
                        "sheet_name": target["sheet_name"], "mapping_id": item["id"],
                        "connection_id": item["data_connection_id"], "target_schema": item["target_schema"],
                        "target_table": item["target_table"],
                        "field_mapping": json.loads(item.get("field_mapping_json") or "{}"),
                    })
                mapping = mapping_by_id[snapshots[0]["mapping_id"]]
                data_connection = connection.execute(select(data_connections).where(data_connections.c.id == mapping["data_connection_id"])).mappings().first()
                if not data_connection or data_connection["status"] != "active" or data_connection["last_test_status"] != "success":
                    raise ValueError("目标数据库连接未启用或尚未测试成功")
                self._ensure_external_write_allowed(data_connection)
                previous_snapshots = json.loads(previous.get("target_mappings_json") or "[]") if previous else []
                if previous and not previous_snapshots:
                    previous_snapshots = [{"connection_id": previous.get("target_connection_id"), "target_schema": previous.get("target_schema"), "target_table": previous.get("target_table")}]
                current_targets = {(item["connection_id"], item["target_schema"], item["target_table"]) for item in snapshots}
                previous_targets = {(item.get("connection_id"), item.get("target_schema"), item.get("target_table")) for item in previous_snapshots}
                if previous and current_targets != previous_targets:
                    raise ValueError("替换批次不能跨目标连接、数据库或数据表，请先作废旧批次")
                sources = [[row["sheet_name"], row["row_number"]] for row in staged]
                result = connection.execute(insert(target_write_operations).values(
                    operation_key=str(uuid.uuid4()), operation_type="commit", batch_id=batch_id,
                    previous_batch_id=previous["id"] if previous else None, table_mapping_id=mapping["id"],
                    data_connection_id=data_connection["id"], target_schema=mapping["target_schema"],
                    target_table=mapping["target_table"], expected_row_count=len(staged),
                    expected_sources_json=json.dumps(sources, ensure_ascii=False), state="prepared", attempt_count=0,
                    mapping_snapshot_json=json.dumps(snapshots, ensure_ascii=False),
                    active_scope_key=f"{batch['template_id']}:{batch['report_month']}", created_by_user_id=actor_id,
                    updated_at=utcnow(),
                ))
                operation_id = result.inserted_primary_key[0]
                connection.execute(update(import_batches).where(import_batches.c.id == batch_id).values(
                    status="committing", table_mapping_id=mapping["id"], target_connection_id=data_connection["id"],
                    target_schema=mapping["target_schema"], target_table=mapping["target_table"],
                    target_field_mapping_json=mapping.get("field_mapping_json") or "{}",
                    target_mappings_json=json.dumps(snapshots, ensure_ascii=False),
                ))
                connection.execute(update(monthly_tasks).where(monthly_tasks.c.id == batch["task_id"]).values(status="committing", updated_at=utcnow()))
        return self._run_commit_operation(operation_id)

    def void_batch(self, actor_id, batch_id, reason, report_month=None):
        operation_id = None
        with self.engine.begin() as connection:
            batch_query = select(import_batches).where(import_batches.c.id == batch_id)
            if self.dialect == "mysql":
                batch_query = batch_query.with_for_update()
            batch = connection.execute(batch_query).mappings().first()
            if not batch:
                raise ValueError("批次不存在")
            if report_month is not None and report_month != batch["report_month"]:
                raise ValueError("所选期间与批次期间不一致，请刷新页面后重试")
            existing_operation = connection.execute(select(target_write_operations).where(
                target_write_operations.c.batch_id == batch_id,
                target_write_operations.c.operation_type == "void",
                target_write_operations.c.state != "finalized",
            )).mappings().first()
            if existing_operation:
                operation_id = existing_operation["id"]
            elif batch["status"] != "committed" or not batch["active_commit_key"]:
                raise ValueError("只有当前有效的已入库记录可以作废")
            task_query = select(monthly_tasks).where(monthly_tasks.c.id == batch["task_id"])
            if self.dialect == "mysql":
                task_query = task_query.with_for_update()
            task = connection.execute(task_query).mappings().first()
            if not task:
                raise ValueError("月度任务不存在")
            self._ensure_task_writable(connection, task)
            if operation_id is None:
                if not batch["table_mapping_id"] or not batch["target_write_count"]:
                    raise ValueError("该批次未写入目标业务表，不能执行作废")
                mapping = connection.execute(select(template_table_mappings).where(template_table_mappings.c.id == batch["table_mapping_id"])).mappings().first()
                connection_id = batch.get("target_connection_id") or (mapping and mapping["data_connection_id"])
                data_connection = connection.execute(select(data_connections).where(data_connections.c.id == connection_id)).mappings().first()
                if not mapping or not data_connection:
                    raise ValueError("历史目标映射或连接不存在")
                self._ensure_external_write_allowed(data_connection)
                snapshots = json.loads(batch.get("target_mappings_json") or "[]")
                result = connection.execute(insert(target_write_operations).values(
                    operation_key=str(uuid.uuid4()), operation_type="void", batch_id=batch_id,
                    table_mapping_id=mapping["id"], data_connection_id=data_connection["id"],
                    target_schema=batch.get("target_schema") or mapping["target_schema"],
                    target_table=batch.get("target_table") or mapping["target_table"],
                    mapping_snapshot_json=json.dumps(snapshots, ensure_ascii=False) if snapshots else None,
                    expected_row_count=batch["target_write_count"], expected_sources_json="[]", state="prepared",
                    attempt_count=0, active_scope_key=batch["active_commit_key"], created_by_user_id=actor_id,
                    last_error=reason, updated_at=utcnow(),
                ))
                operation_id = result.inserted_primary_key[0]
                connection.execute(update(import_batches).where(import_batches.c.id == batch_id).values(status="voiding", void_reason=reason, voided_by_user_id=actor_id))
                connection.execute(update(monthly_tasks).where(monthly_tasks.c.id == batch["task_id"]).values(status="voiding", updated_at=utcnow()))
        return self._run_void_operation(operation_id)

    def _reflect_external_target_table(self, target_connection, target_schema, target_table):
        self._validate_target_schema(target_schema)
        available = inspect(target_connection).get_table_names()
        if target_table not in available:
            raise ValueError("目标表不存在，已停止操作")
        return Table(
            target_table,
            MetaData(),
            autoload_with=target_connection,
        )

    def _operation_context(self, operation_id):
        with self.engine.connect() as connection:
            operation = connection.execute(select(target_write_operations).where(target_write_operations.c.id == operation_id)).mappings().first()
            if not operation:
                raise ValueError("目标写入操作不存在")
            batch = connection.execute(select(import_batches).where(import_batches.c.id == operation["batch_id"])).mappings().first()
            mapping = connection.execute(select(template_table_mappings).where(template_table_mappings.c.id == operation["table_mapping_id"])).mappings().first()
            data_connection = connection.execute(select(data_connections).where(data_connections.c.id == operation["data_connection_id"])).mappings().first()
            staged = connection.execute(select(staging_records).where(staging_records.c.import_batch_id == operation["batch_id"]).order_by(staging_records.c.id)).mappings().all()
            previous = connection.execute(select(import_batches).where(import_batches.c.id == operation["previous_batch_id"])).mappings().first() if operation["previous_batch_id"] else None
            previous_ledger = connection.execute(select(target_write_rows).where(target_write_rows.c.import_batch_id == operation["previous_batch_id"]).order_by(target_write_rows.c.row_index)).mappings().all() if operation["previous_batch_id"] else []
            actor = connection.execute(select(users).where(users.c.id == operation["created_by_user_id"])).mappings().first()
        if not batch or not mapping or not data_connection or not actor:
            raise ValueError("目标写入操作上下文不完整")
        return operation, batch, mapping, data_connection, staged, previous, previous_ledger, actor

    @staticmethod
    def _target_rows_by_source(target_connection, target, batch_id, primary_keys, source_sheet_name=None):
        query = select(*primary_keys, target.c.source_sheet_name, target.c.source_row_number).where(target.c.import_batch_id == batch_id)
        if source_sheet_name is not None:
            query = query.where(target.c.source_sheet_name == source_sheet_name)
        rows = target_connection.execute(query).mappings().all()
        result = {}
        for row in rows:
            source = (row["source_sheet_name"], row["source_row_number"])
            if source in result:
                raise ValueError("目标表存在重复源行，需要人工复核")
            result[source] = {column.name: row[column.name] for column in primary_keys}
        return result

    def _managed_target_batch_ids(self, connection_id, target_schema, target_table, report_month):
        """Return active target batches that are still represented by this app ledger."""
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(target_write_operations, import_batches.c.report_month, import_batches.c.status.label("batch_status"))
                .join(import_batches, import_batches.c.id == target_write_operations.c.batch_id)
                .where(
                    target_write_operations.c.operation_type == "commit",
                    import_batches.c.report_month == report_month,
                    import_batches.c.status.in_(("committing", "committed", "recovery_required")),
                )
            ).mappings().all()
        managed = set()
        for row in rows:
            snapshots = json.loads(row.get("mapping_snapshot_json") or "[]") or [{
                "connection_id": row.get("data_connection_id"),
                "target_schema": row.get("target_schema"),
                "target_table": row.get("target_table"),
            }]
            if any(
                item.get("connection_id") == connection_id
                and item.get("target_schema") == target_schema
                and item.get("target_table") == target_table
                for item in snapshots
            ):
                managed.add(row["batch_id"])
        return managed

    @staticmethod
    def _ensure_target_scope_managed(target_connection, target, report_month, current_batch_id, managed_batch_ids):
        required = {"report_month", "import_batch_id"}
        if not required.issubset(target.c.keys()):
            raise ValueError(f"目标表缺少系统字段：{'、'.join(sorted(required - set(target.c.keys())))}")
        scope_rows = target_connection.execute(
            select(target.c.import_batch_id, func.count().label("row_count"))
            .where(target.c.report_month == report_month)
            .group_by(target.c.import_batch_id)
        ).all()
        unknown_rows = sum(
            row.row_count for row in scope_rows
            if row.import_batch_id != current_batch_id and row.import_batch_id not in managed_batch_ids
        )
        if unknown_rows:
            raise ValueError(
                f"目标表已存在 {report_month} 的 {unknown_rows} 行非当前平台台账数据，已停止写入，需要人工复核"
            )

    def _build_target_rows(self, target, batch, staged, field_mapping, actor):
        tracking_fields = {"import_batch_id", "source_sheet_name", "source_row_number"}
        missing = sorted(tracking_fields - set(target.c.keys()))
        if missing:
            raise ValueError(f"目标表缺少系统字段：{'、'.join(missing)}")
        # Target business tables use MySQL DATETIME columns without timezone
        # information, so persist the configured business wall clock rather
        # than an ambiguous naive UTC value.
        import_time = shanghai_now().replace(tzinfo=None)
        target_rows = []
        sources = []
        for staged_row in staged:
            source_payload = json.loads(staged_row["payload_json"])
            payload = {field_mapping.get(name, name): value for name, value in source_payload.items()}
            system_values = {
                "report_month": batch["report_month"], "import_batch_id": batch["id"],
                "source_sheet_name": staged_row["sheet_name"], "source_row_number": staged_row["row_number"],
                "data_import_time": import_time, "data_import_user": actor["display_name"],
            }
            payload.update({name: value for name, value in system_values.items() if name in target.c})
            unknown = sorted(set(payload) - set(target.c.keys()))
            if unknown:
                raise ValueError(f"目标表缺少字段：{'、'.join(unknown)}")
            target_rows.append(payload)
            sources.append((staged_row["sheet_name"], staged_row["row_number"]))
        if len(set(sources)) != len(sources):
            raise ValueError("源工作表与源行号不唯一，已停止入库")
        payload_fields = set().union(*(row.keys() for row in target_rows))
        for row in target_rows:
            for field in payload_fields:
                row.setdefault(field, None)
        return target_rows, sources

    def _mark_operation_failure(self, operation_id, message, manual=False):
        safe_message = str(message)[:500]
        with self.engine.begin() as connection:
            operation = connection.execute(select(target_write_operations).where(target_write_operations.c.id == operation_id)).mappings().first()
            if not operation:
                raise ValueError(safe_message)
            attempts = operation["attempt_count"] + 1
            state = "manual_review" if manual or attempts >= 8 else "retryable_failed"
            connection.execute(update(target_write_operations).where(target_write_operations.c.id == operation_id).values(state=state, attempt_count=attempts, last_error=safe_message, updated_at=utcnow()))
            connection.execute(update(import_batches).where(import_batches.c.id == operation["batch_id"]).values(status="recovery_required"))
            batch = connection.execute(select(import_batches).where(import_batches.c.id == operation["batch_id"])).mappings().first()
            if batch.get("task_id"):
                connection.execute(
                    update(monthly_tasks)
                    .where(monthly_tasks.c.id == batch["task_id"])
                    .values(status="recovery_required", current_batch_id=batch["id"], updated_at=utcnow())
                )
            return self._batch_payload(connection, batch)

    def _run_commit_operation(self, operation_id, allow_empty_target_rebuild=False):
        with self.engine.connect() as connection:
            operation_row = connection.execute(
                select(target_write_operations).where(target_write_operations.c.id == operation_id)
            ).mappings().first()
        snapshots = json.loads(operation_row.get("mapping_snapshot_json") or "[]") if operation_row else []
        if len(snapshots) > 1:
            return self._run_multi_commit_operation(operation_id, snapshots, allow_empty_target_rebuild=allow_empty_target_rebuild)
        try:
            operation, batch, mapping, data_connection, staged, previous, previous_ledger, actor = self._operation_context(operation_id)
            if operation["state"] == "finalized":
                return self.get_batch({"id": actor["id"], "role": "admin"}, batch["id"])
            self._ensure_external_write_allowed(data_connection)
            target_engine = self._mysql_engine_for_row(data_connection)
            managed_batch_ids = self._managed_target_batch_ids(
                data_connection["id"], operation["target_schema"], operation["target_table"], batch["report_month"]
            )
            with target_engine.begin() as target_connection:
                target = self._reflect_external_target_table(target_connection, operation["target_schema"], operation["target_table"])
                primary_keys = list(target.primary_key.columns)
                if not primary_keys:
                    raise ValueError("目标表缺少主键，不能执行入库")
                target_rows, sources = self._build_target_rows(target, batch, staged, json.loads(batch.get("target_field_mapping_json") or mapping.get("field_mapping_json") or "{}"), actor)
                inserted = self._target_rows_by_source(target_connection, target, batch["id"], primary_keys)
                self._ensure_target_scope_managed(
                    target_connection, target, batch["report_month"], batch["id"], managed_batch_ids
                )
                if inserted and set(inserted) != set(sources):
                    raise ValueError("目标表存在无法确认的部分批次数据，需要人工复核")
                if not inserted:
                    if previous:
                        if len(previous_ledger) != previous["target_write_count"]:
                            raise ValueError("目标表写入台账不完整，需要人工复核")
                        current_primary_keys = target_connection.execute(select(*primary_keys).where(target.c.import_batch_id == previous["id"])).mappings().all()
                        target_signatures = sorted(primary_key_signature({column.name: row[column.name] for column in primary_keys}) for row in current_primary_keys)
                        ledger_signatures = sorted(primary_key_signature(json.loads(row["primary_key_json"])) for row in previous_ledger)
                        if target_signatures != ledger_signatures:
                            scope_rows = target_connection.execute(
                                select(*primary_keys).where(target.c.report_month == batch["report_month"]).with_for_update()
                            ).mappings().all()
                            if not allow_empty_target_rebuild or target_signatures or scope_rows:
                                raise ValueError("目标表数据与写入台账不一致，需要人工复核")
                        else:
                            deleted = target_connection.execute(delete(target).where(target.c.import_batch_id == previous["id"]))
                            if deleted.rowcount != len(previous_ledger):
                                raise ValueError("目标表删除数量与写入台账不一致，需要人工复核")
                    for target_chunk in chunked(target_rows):
                        target_connection.execute(insert(target), target_chunk)
                    inserted = self._target_rows_by_source(target_connection, target, batch["id"], primary_keys)
                    if set(inserted) != set(sources):
                        raise ValueError("目标表写入结果与待入库明细不一致，需要人工复核")
            with self.engine.begin() as connection:
                connection.execute(update(target_write_operations).where(target_write_operations.c.id == operation_id).values(state="target_committed", target_committed_at=utcnow(), attempt_count=operation["attempt_count"] + 1, last_error=None, updated_at=utcnow()))
            with self.engine.begin() as connection:
                current_operation = connection.execute(select(target_write_operations).where(target_write_operations.c.id == operation_id)).mappings().first()
                if current_operation["state"] == "finalized":
                    row = connection.execute(select(import_batches).where(import_batches.c.id == batch["id"])).mappings().first()
                    return self._batch_payload(connection, row)
                template = connection.execute(select(template_definitions).where(template_definitions.c.id == batch["template_id"])).mappings().first()
                if previous:
                    connection.execute(delete(target_write_rows).where(target_write_rows.c.import_batch_id == previous["id"]))
                    connection.execute(update(import_batches).where(import_batches.c.id == previous["id"]).values(status="superseded", active_commit_key=None))
                if not connection.execute(select(target_write_rows.c.id).where(target_write_rows.c.import_batch_id == batch["id"]).limit(1)).first():
                    ledger_rows = [{"import_batch_id": batch["id"], "table_mapping_id": mapping["id"], "row_index": index, "primary_key_json": json.dumps(inserted[source], ensure_ascii=False, default=str)} for index, source in enumerate(sources, 1)]
                    for ledger_chunk in chunked(ledger_rows):
                        connection.execute(insert(target_write_rows), ledger_chunk)
                active_key = f"{batch['template_id']}:{batch['report_month']}"
                connection.execute(update(import_batches).where(import_batches.c.id == batch["id"]).values(status="committed", committed_at=utcnow(), active_commit_key=active_key, target_write_count=len(sources)))
                connection.execute(update(monthly_tasks).where(monthly_tasks.c.id == batch["task_id"]).values(status="committed", current_batch_id=batch["id"], updated_at=utcnow()))
                connection.execute(update(template_table_mappings).where(template_table_mappings.c.id == mapping["id"]).values(last_written_at=utcnow(), updated_at=utcnow()))
                connection.execute(update(target_write_operations).where(target_write_operations.c.id == operation_id).values(state="finalized", active_scope_key=None, finalized_at=utcnow(), updated_at=utcnow()))
                self.audit(connection, actor["id"], "imports.rebuild_empty_target" if allow_empty_target_rebuild else "imports.commit", "import_batch", str(batch["id"]), "从当前批次重建空目标表" if allow_empty_target_rebuild else "确认入库", {"report_month": batch["report_month"], "replaced_batch_id": previous["id"] if previous else None})
                row = connection.execute(select(import_batches).where(import_batches.c.id == batch["id"])).mappings().first()
                return self._batch_payload(connection, row)
        except (ValueError, SQLAlchemyError) as exc:
            manual = "人工复核" in str(exc) or "不一致" in str(exc)
            return self._mark_operation_failure(operation_id, exc, manual=manual)

    def _run_multi_commit_operation(self, operation_id, snapshots, allow_empty_target_rebuild=False):
        try:
            with self.engine.connect() as connection:
                operation = connection.execute(select(target_write_operations).where(target_write_operations.c.id == operation_id)).mappings().one()
                batch = connection.execute(select(import_batches).where(import_batches.c.id == operation["batch_id"])).mappings().one()
                data_connection = connection.execute(select(data_connections).where(data_connections.c.id == operation["data_connection_id"])).mappings().one()
                staged = connection.execute(select(staging_records).where(staging_records.c.import_batch_id == batch["id"]).order_by(staging_records.c.id)).mappings().all()
                previous = connection.execute(select(import_batches).where(import_batches.c.id == operation["previous_batch_id"])).mappings().first() if operation["previous_batch_id"] else None
                previous_ledger = connection.execute(select(target_write_rows).where(target_write_rows.c.import_batch_id == operation["previous_batch_id"]).order_by(target_write_rows.c.row_index)).mappings().all() if previous else []
                actor = connection.execute(select(users).where(users.c.id == operation["created_by_user_id"])).mappings().one()
            if operation["state"] == "finalized":
                return self.get_batch({"id": actor["id"], "role": "admin"}, batch["id"])
            self._ensure_external_write_allowed(data_connection)
            target_engine = self._mysql_engine_for_row(data_connection)
            inserted_by_mapping = {}
            sources_by_mapping = {}
            with target_engine.begin() as target_connection:
                contexts = []
                any_current = False
                all_current = True
                for snapshot in snapshots:
                    target = self._reflect_external_target_table(target_connection, snapshot["target_schema"], snapshot["target_table"])
                    primary_keys = list(target.primary_key.columns)
                    if not primary_keys:
                        raise ValueError(f"目标表 {snapshot['target_table']} 缺少主键，不能执行入库")
                    sheet_rows = [row for row in staged if row["sheet_name"] == snapshot["sheet_name"]]
                    if not sheet_rows:
                        raise ValueError(f"工作表 {snapshot['sheet_name']} 没有可入库明细")
                    target_rows, sources = self._build_target_rows(target, batch, sheet_rows, snapshot["field_mapping"], actor)
                    inserted = self._target_rows_by_source(target_connection, target, batch["id"], primary_keys, source_sheet_name=snapshot["sheet_name"])
                    managed_batch_ids = self._managed_target_batch_ids(
                        data_connection["id"], snapshot["target_schema"], snapshot["target_table"], batch["report_month"]
                    )
                    self._ensure_target_scope_managed(
                        target_connection, target, batch["report_month"], batch["id"], managed_batch_ids
                    )
                    if inserted and set(inserted) != set(sources):
                        raise ValueError(f"目标表 {snapshot['target_table']} 存在无法确认的部分批次数据，需要人工复核")
                    any_current = any_current or bool(inserted)
                    all_current = all_current and bool(inserted)
                    contexts.append((snapshot, target, primary_keys, target_rows, sources, inserted))
                if any_current and not all_current:
                    raise ValueError("多目标表存在不完整的批次数据，需要人工复核")
                if not any_current:
                    if previous:
                        previous_snapshots = json.loads(previous.get("target_mappings_json") or "[]")
                        ledger_by_mapping = defaultdict(list)
                        for ledger_row in previous_ledger:
                            ledger_by_mapping[ledger_row["table_mapping_id"]].append(ledger_row)
                        if len(previous_ledger) != previous["target_write_count"]:
                            raise ValueError("目标表写入台账不完整，需要人工复核")
                        for old in previous_snapshots:
                            old_target = self._reflect_external_target_table(target_connection, old["target_schema"], old["target_table"])
                            old_keys = list(old_target.primary_key.columns)
                            old_ledger = ledger_by_mapping[old["mapping_id"]]
                            current_rows = target_connection.execute(select(*old_keys).where(old_target.c.import_batch_id == previous["id"], old_target.c.source_sheet_name == old["sheet_name"])).mappings().all()
                            target_signatures = sorted(primary_key_signature({column.name: row[column.name] for column in old_keys}) for row in current_rows)
                            ledger_signatures = sorted(primary_key_signature(json.loads(row["primary_key_json"])) for row in old_ledger)
                            if target_signatures != ledger_signatures:
                                scope_rows = target_connection.execute(
                                    select(*old_keys).where(old_target.c.report_month == batch["report_month"]).with_for_update()
                                ).mappings().all()
                                if not allow_empty_target_rebuild or target_signatures or scope_rows:
                                    raise ValueError(f"目标表 {old['target_table']} 数据与写入台账不一致，需要人工复核")
                            else:
                                deleted = target_connection.execute(delete(old_target).where(old_target.c.import_batch_id == previous["id"], old_target.c.source_sheet_name == old["sheet_name"]))
                                if deleted.rowcount != len(old_ledger):
                                    raise ValueError(f"目标表 {old['target_table']} 删除数量与写入台账不一致，需要人工复核")
                    for snapshot, target, primary_keys, target_rows, sources, _inserted in contexts:
                        for target_chunk in chunked(target_rows):
                            target_connection.execute(insert(target), target_chunk)
                        inserted = self._target_rows_by_source(target_connection, target, batch["id"], primary_keys, source_sheet_name=snapshot["sheet_name"])
                        if set(inserted) != set(sources):
                            raise ValueError(f"目标表 {snapshot['target_table']} 写入结果与待入库明细不一致，需要人工复核")
                        inserted_by_mapping[snapshot["mapping_id"]] = inserted
                        sources_by_mapping[snapshot["mapping_id"]] = sources
                else:
                    for snapshot, _target, _keys, _rows, sources, inserted in contexts:
                        inserted_by_mapping[snapshot["mapping_id"]] = inserted
                        sources_by_mapping[snapshot["mapping_id"]] = sources
            with self.engine.begin() as connection:
                connection.execute(update(target_write_operations).where(target_write_operations.c.id == operation_id).values(state="target_committed", target_committed_at=utcnow(), attempt_count=operation["attempt_count"] + 1, last_error=None, updated_at=utcnow()))
            with self.engine.begin() as connection:
                if previous:
                    connection.execute(delete(target_write_rows).where(target_write_rows.c.import_batch_id == previous["id"]))
                    connection.execute(update(import_batches).where(import_batches.c.id == previous["id"]).values(status="superseded", active_commit_key=None))
                if not connection.execute(select(target_write_rows.c.id).where(target_write_rows.c.import_batch_id == batch["id"]).limit(1)).first():
                    ledger_rows = []
                    row_index = 1
                    for snapshot in snapshots:
                        mapping_id = snapshot["mapping_id"]
                        for source in sources_by_mapping[mapping_id]:
                            ledger_rows.append({"import_batch_id": batch["id"], "table_mapping_id": mapping_id, "row_index": row_index, "primary_key_json": json.dumps(inserted_by_mapping[mapping_id][source], ensure_ascii=False, default=str)})
                            row_index += 1
                    for ledger_chunk in chunked(ledger_rows):
                        connection.execute(insert(target_write_rows), ledger_chunk)
                active_key = f"{batch['template_id']}:{batch['report_month']}"
                connection.execute(update(import_batches).where(import_batches.c.id == batch["id"]).values(status="committed", committed_at=utcnow(), active_commit_key=active_key, target_write_count=sum(len(items) for items in sources_by_mapping.values())))
                connection.execute(update(monthly_tasks).where(monthly_tasks.c.id == batch["task_id"]).values(status="committed", current_batch_id=batch["id"], updated_at=utcnow()))
                connection.execute(update(template_table_mappings).where(template_table_mappings.c.id.in_([item["mapping_id"] for item in snapshots])).values(last_written_at=utcnow(), updated_at=utcnow()))
                connection.execute(update(target_write_operations).where(target_write_operations.c.id == operation_id).values(state="finalized", active_scope_key=None, finalized_at=utcnow(), updated_at=utcnow()))
                self.audit(connection, actor["id"], "imports.rebuild_empty_target" if allow_empty_target_rebuild else "imports.commit", "import_batch", str(batch["id"]), "从当前批次重建空目标表" if allow_empty_target_rebuild else "确认多工作表原子入库", {"report_month": batch["report_month"], "targets": [{"sheet_name": item["sheet_name"], "table": item["target_table"]} for item in snapshots], "replaced_batch_id": previous["id"] if previous else None})
                row = connection.execute(select(import_batches).where(import_batches.c.id == batch["id"])).mappings().one()
                return self._batch_payload(connection, row)
        except (ValueError, SQLAlchemyError) as exc:
            manual = "人工复核" in str(exc) or "不一致" in str(exc)
            return self._mark_operation_failure(operation_id, exc, manual=manual)

    def _run_void_operation(self, operation_id):
        with self.engine.connect() as connection:
            operation_row = connection.execute(select(target_write_operations).where(target_write_operations.c.id == operation_id)).mappings().first()
        snapshots = json.loads(operation_row.get("mapping_snapshot_json") or "[]") if operation_row else []
        if len(snapshots) > 1:
            return self._run_multi_void_operation(operation_id, snapshots)
        try:
            operation, batch, mapping, data_connection, _staged, _previous, _previous_ledger, actor = self._operation_context(operation_id)
            self._ensure_external_write_allowed(data_connection)
            with self.engine.connect() as connection:
                ledger = connection.execute(select(target_write_rows).where(target_write_rows.c.import_batch_id == batch["id"]).order_by(target_write_rows.c.row_index)).mappings().all()
            if len(ledger) != batch["target_write_count"]:
                raise ValueError("目标表写入台账不完整，需要人工复核")
            target_engine = self._mysql_engine_for_row(data_connection)
            with target_engine.begin() as target_connection:
                target = self._reflect_external_target_table(target_connection, operation["target_schema"], operation["target_table"])
                primary_keys = list(target.primary_key.columns)
                current_rows = target_connection.execute(select(*primary_keys).where(target.c.import_batch_id == batch["id"])).mappings().all()
                if current_rows:
                    target_signatures = sorted(primary_key_signature({column.name: row[column.name] for column in primary_keys}) for row in current_rows)
                    ledger_signatures = sorted(primary_key_signature(json.loads(row["primary_key_json"])) for row in ledger)
                    if target_signatures != ledger_signatures:
                        raise ValueError("目标表数据与写入台账不一致，需要人工复核")
                    deleted = target_connection.execute(delete(target).where(target.c.import_batch_id == batch["id"]))
                    if deleted.rowcount != len(ledger):
                        raise ValueError("目标表删除数量与写入台账不一致，需要人工复核")
            with self.engine.begin() as connection:
                connection.execute(delete(target_write_rows).where(target_write_rows.c.import_batch_id == batch["id"]))
                connection.execute(update(import_batches).where(import_batches.c.id == batch["id"]).values(status="voided", voided_at=utcnow(), active_commit_key=None))
                connection.execute(update(monthly_tasks).where(monthly_tasks.c.id == batch["task_id"]).values(status="voided", updated_at=utcnow()))
                connection.execute(update(target_write_operations).where(target_write_operations.c.id == operation_id).values(state="finalized", active_scope_key=None, target_committed_at=utcnow(), finalized_at=utcnow(), last_error=None, updated_at=utcnow()))
                self.audit(connection, actor["id"], "imports.void", "import_batch", str(batch["id"]), "作废入库记录", {"reason": batch["void_reason"]})
                row = connection.execute(select(import_batches).where(import_batches.c.id == batch["id"])).mappings().first()
                return self._batch_payload(connection, row)
        except (ValueError, SQLAlchemyError) as exc:
            manual = "人工复核" in str(exc) or "不一致" in str(exc)
            return self._mark_operation_failure(operation_id, exc, manual=manual)

    def _run_multi_void_operation(self, operation_id, snapshots):
        try:
            with self.engine.connect() as connection:
                operation = connection.execute(select(target_write_operations).where(target_write_operations.c.id == operation_id)).mappings().one()
                batch = connection.execute(select(import_batches).where(import_batches.c.id == operation["batch_id"])).mappings().one()
                data_connection = connection.execute(select(data_connections).where(data_connections.c.id == operation["data_connection_id"])).mappings().one()
                actor = connection.execute(select(users).where(users.c.id == operation["created_by_user_id"])).mappings().one()
                ledger = connection.execute(select(target_write_rows).where(target_write_rows.c.import_batch_id == batch["id"]).order_by(target_write_rows.c.row_index)).mappings().all()
            if len(ledger) != batch["target_write_count"]:
                raise ValueError("目标表写入台账不完整，需要人工复核")
            ledger_by_mapping = defaultdict(list)
            for row in ledger:
                ledger_by_mapping[row["table_mapping_id"]].append(row)
            self._ensure_external_write_allowed(data_connection)
            target_engine = self._mysql_engine_for_row(data_connection)
            with target_engine.begin() as target_connection:
                for snapshot in snapshots:
                    target = self._reflect_external_target_table(target_connection, snapshot["target_schema"], snapshot["target_table"])
                    primary_keys = list(target.primary_key.columns)
                    current_rows = target_connection.execute(select(*primary_keys).where(target.c.import_batch_id == batch["id"])).mappings().all()
                    target_signatures = sorted(primary_key_signature({column.name: row[column.name] for column in primary_keys}) for row in current_rows)
                    sheet_ledger = ledger_by_mapping[snapshot["mapping_id"]]
                    ledger_signatures = sorted(primary_key_signature(json.loads(row["primary_key_json"])) for row in sheet_ledger)
                    if target_signatures != ledger_signatures:
                        raise ValueError(f"目标表 {snapshot['target_table']} 数据与写入台账不一致，需要人工复核")
                    deleted = target_connection.execute(delete(target).where(target.c.import_batch_id == batch["id"]))
                    if deleted.rowcount != len(sheet_ledger):
                        raise ValueError(f"目标表 {snapshot['target_table']} 删除数量与写入台账不一致，需要人工复核")
            with self.engine.begin() as connection:
                connection.execute(delete(target_write_rows).where(target_write_rows.c.import_batch_id == batch["id"]))
                connection.execute(update(import_batches).where(import_batches.c.id == batch["id"]).values(status="voided", voided_at=utcnow(), active_commit_key=None))
                connection.execute(update(monthly_tasks).where(monthly_tasks.c.id == batch["task_id"]).values(status="voided", updated_at=utcnow()))
                connection.execute(update(target_write_operations).where(target_write_operations.c.id == operation_id).values(state="finalized", active_scope_key=None, target_committed_at=utcnow(), finalized_at=utcnow(), last_error=None, updated_at=utcnow()))
                self.audit(connection, actor["id"], "imports.void", "import_batch", str(batch["id"]), "作废多工作表入库记录", {"reason": batch["void_reason"], "targets": [item["target_table"] for item in snapshots]})
                row = connection.execute(select(import_batches).where(import_batches.c.id == batch["id"])).mappings().one()
                return self._batch_payload(connection, row)
        except (ValueError, SQLAlchemyError) as exc:
            manual = "人工复核" in str(exc) or "不一致" in str(exc)
            return self._mark_operation_failure(operation_id, exc, manual=manual)

    def retry_write_operation(self, operation_id):
        with self.engine.connect() as connection:
            operation = connection.execute(select(target_write_operations).where(target_write_operations.c.id == operation_id)).mappings().first()
        if not operation:
            raise ValueError("目标写入操作不存在")
        if operation["state"] == "finalized":
            raise ValueError("目标写入操作已经完成")
        if operation["state"] == "manual_review":
            raise ValueError("目标写入操作需要人工复核，不能自动重试")
        return self._run_commit_operation(operation_id) if operation["operation_type"] == "commit" else self._run_void_operation(operation_id)

    def rebuild_empty_target_operation(self, current_user, operation_id):
        with self.engine.connect() as connection:
            operation = connection.execute(
                select(target_write_operations).where(target_write_operations.c.id == operation_id)
            ).mappings().first()
            if not operation:
                raise ValueError("目标写入操作不存在")
            batch = connection.execute(
                select(import_batches).where(import_batches.c.id == operation["batch_id"])
            ).mappings().first()
            task = connection.execute(
                select(monthly_tasks).where(monthly_tasks.c.id == batch["task_id"])
            ).mappings().first() if batch and batch.get("task_id") else None
            if not batch or not task:
                raise ValueError("当前批次没有有效的填报任务")
            if current_user["role"] != "admin":
                raise PermissionError("仅管理员可以确认从当前批次重建空目标表")
            self._ensure_task_writable(connection, task)
            if operation["operation_type"] != "commit" or operation["state"] != "manual_review":
                raise ValueError("当前写入操作不处于可人工恢复状态")
            if batch["status"] != "recovery_required" or not operation["previous_batch_id"]:
                raise ValueError("当前批次不符合空目标表恢复条件")
        return self._run_commit_operation(operation_id, allow_empty_target_rebuild=True)

    def list_write_operations(self):
        with self.engine.connect() as connection:
            rows = connection.execute(select(target_write_operations).order_by(target_write_operations.c.id.desc())).mappings().all()
            return [self._json_ready(dict(row)) for row in rows]

    def reconcile_pending_operations(self, limit=10):
        if not settings.external_writes_enabled:
            return []
        with self.engine.connect() as connection:
            operation_ids = list(connection.execute(
                select(target_write_operations.c.id)
                .where(target_write_operations.c.state.in_(("prepared", "target_committed", "retryable_failed")))
                .order_by(target_write_operations.c.id)
                .limit(limit)
            ).scalars())
        return [self.retry_write_operation(operation_id) for operation_id in operation_ids]

    def get_batch(self, current_user, batch_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(import_batches).where(import_batches.c.id == batch_id)).mappings().first()
            if not row:
                return None
            payload = self._batch_payload(connection, row)
            owner = payload.get("owner")
            if current_user["role"] != "admin" and (not owner or owner.get("id") != current_user["id"]):
                return None
            return payload

    def list_batches(self, current_user, report_month=None, status=None):
        with self.engine.connect() as connection:
            query = select(import_batches).order_by(import_batches.c.id.desc())
            conditions = []
            if report_month:
                conditions.append(import_batches.c.report_month == report_month)
            if status:
                conditions.append(import_batches.c.status == status)
            if conditions:
                query = query.where(and_(*conditions))
            rows = connection.execute(query).mappings().all()
            if not rows:
                return []

            task_ids = {row["task_id"] for row in rows if row["task_id"]}
            task_rows = {
                row["id"]: row
                for row in connection.execute(select(monthly_tasks).where(monthly_tasks.c.id.in_(task_ids))).mappings().all()
            } if task_ids else {}
            if current_user["role"] != "admin":
                rows = [
                    row for row in rows
                    if row["task_id"] in task_rows and task_rows[row["task_id"]]["owner_user_id"] == current_user["id"]
                ]
                if not rows:
                    return []

            batch_ids = {row["id"] for row in rows}
            template_ids = {row["template_id"] for row in rows}
            template_rows = {
                row["id"]: row
                for row in connection.execute(select(template_definitions).where(template_definitions.c.id.in_(template_ids))).mappings().all()
            }
            raw_ids = {row["raw_file_id"] for row in rows}
            raw_rows = {
                row["id"]: row
                for row in connection.execute(select(raw_files).where(raw_files.c.id.in_(raw_ids))).mappings().all()
            }
            error_rows = connection.execute(
                select(validation_errors)
                .where(validation_errors.c.import_batch_id.in_(batch_ids))
                .order_by(validation_errors.c.import_batch_id, validation_errors.c.id)
            ).mappings().all()
            errors_by_batch = {}
            for error in error_rows:
                grouped = errors_by_batch.setdefault(error["import_batch_id"], [])
                if len(grouped) < 50:
                    grouped.append(dict(error))

            relevant_tasks = [task_rows[row["task_id"]] for row in rows if row["task_id"] in task_rows]
            user_ids = {task["owner_user_id"] for task in relevant_tasks if task["owner_user_id"]}
            user_ids.update(row["voided_by_user_id"] for row in rows if row["voided_by_user_id"])
            user_rows = {
                row["id"]: self.public_user(row)
                for row in connection.execute(select(users).where(users.c.id.in_(user_ids))).mappings().all()
            } if user_ids else {}
            months = {task["report_month"] for task in relevant_tasks}
            period_rows = {
                row["report_month"]: row
                for row in connection.execute(select(reporting_periods).where(reporting_periods.c.report_month.in_(months))).mappings().all()
            } if months else {}

            mapping_ids = {row["table_mapping_id"] for row in rows if row["table_mapping_id"]}
            mapping_rows = {
                row["id"]: row
                for row in connection.execute(select(template_table_mappings).where(template_table_mappings.c.id.in_(mapping_ids))).mappings().all()
            } if mapping_ids else {}
            mapping_version_ids = {row["template_version_id"] for row in mapping_rows.values()}
            mapping_versions = {
                row["id"]: row
                for row in connection.execute(select(template_versions).where(template_versions.c.id.in_(mapping_version_ids))).mappings().all()
            } if mapping_version_ids else {}
            mapping_connection_ids = {row["data_connection_id"] for row in mapping_rows.values()}
            mapping_connections = {
                row["id"]: row
                for row in connection.execute(select(data_connections).where(data_connections.c.id.in_(mapping_connection_ids))).mappings().all()
            } if mapping_connection_ids else {}

            now = utcnow()
            payloads = []
            for row in rows:
                template = template_rows[row["template_id"]]
                raw = raw_rows[row["raw_file_id"]]
                task = task_rows.get(row["task_id"])
                mapping = mapping_rows.get(row["table_mapping_id"])
                mapping_payload = None
                if mapping:
                    version = mapping_versions[mapping["template_version_id"]]
                    mapping_payload = self._mapping_payload_from_rows(
                        mapping,
                        version,
                        template_rows[version["template_id"]],
                        mapping_connections[mapping["data_connection_id"]],
                    )
                payload = {
                    **dict(row),
                    "summary": {key: value for key, value in json.loads(row["summary_json"]).items() if not key.startswith("_")},
                    "template": {"code": template["code"], "name": template["name"], "short_name": template["short_name"]},
                    "raw_file": {
                        "id": raw["id"],
                        "original_filename": raw["original_filename"],
                        "sha256": raw["sha256"],
                        "size_bytes": raw["size_bytes"],
                    },
                    "owner": user_rows.get(task["owner_user_id"]) if task else None,
                    "access": self._task_access_from_period(task, period_rows.get(task["report_month"]), now=now) if task else None,
                    "voided_by": user_rows.get(row["voided_by_user_id"]),
                    "table_mapping": mapping_payload,
                    "errors": errors_by_batch.get(row["id"], []),
                    "commit_readiness": self._template_version_commit_readiness(
                        connection, row["template_version_id"], live_validate=False
                    ),
                }
                payload.pop("summary_json", None)
                payload.pop("active_commit_key", None)
                payloads.append(self._json_ready(payload))
            return payloads

    def get_staging_preview(self, current_user, batch_id, page=1, page_size=20, sheet_name=None):
        batch = self.get_batch(current_user, batch_id)
        if not batch:
            return None
        with self.engine.connect() as connection:
            stored_summary = json.loads(
                connection.execute(select(import_batches.c.summary_json).where(import_batches.c.id == batch_id)).scalar_one()
            )
            sheet_count_rows = connection.execute(
                select(staging_records.c.sheet_name, func.count())
                .where(staging_records.c.import_batch_id == batch_id)
                .group_by(staging_records.c.sheet_name)
                .order_by(func.min(staging_records.c.id))
            ).all()
            sheet_counts = {name: count for name, count in sheet_count_rows}
            sheet_names = stored_summary.get("_preview_sheets") or list(sheet_counts)
            selected_sheet = sheet_name if sheet_name in sheet_counts else (sheet_names[0] if len(sheet_names) > 1 else None)
            row_condition = staging_records.c.import_batch_id == batch_id
            if selected_sheet:
                row_condition = row_condition & (staging_records.c.sheet_name == selected_sheet)
            total_rows = connection.execute(
                select(func.count()).select_from(staging_records).where(row_condition)
            ).scalar_one()
            total_pages = (total_rows + page_size - 1) // page_size if total_rows else 0
            rows = connection.execute(
                select(staging_records)
                .where(row_condition)
                .order_by(staging_records.c.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).mappings().all()
            parsed = [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]
            fields_by_sheet = stored_summary.get("_preview_fields_by_sheet") or {}
            fields = fields_by_sheet.get(selected_sheet) if selected_sheet else stored_summary.get("_preview_fields")
            if fields is None or sheet_names is None:
                # Compatibility fallback for batches created before preview
                # metadata was stored in the existing summary JSON.
                metadata_rows = connection.execute(
                    select(staging_records.c.sheet_name, staging_records.c.payload_json)
                    .where(row_condition)
                    .order_by(staging_records.c.id)
                ).all()
                fields = []
                discovered_sheet_names = []
                for sheet_name, payload_json in metadata_rows:
                    if sheet_name not in discovered_sheet_names:
                        discovered_sheet_names.append(sheet_name)
                    for field in json.loads(payload_json).keys():
                        if field not in fields:
                            fields.append(field)
                if not sheet_names:
                    sheet_names = discovered_sheet_names
            return {
                "batch": batch,
                "rows": parsed,
                "fields": fields,
                "sheet_names": sheet_names,
                "selected_sheet": selected_sheet,
                "sheet_counts": sheet_counts,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_rows": total_rows,
                    "total_pages": total_pages,
                },
            }

    def get_raw_file_for_batch(self, current_user, batch_id):
        if not self.get_batch(current_user, batch_id):
            return None
        with self.engine.connect() as connection:
            return connection.execute(
                select(raw_files)
                .join(import_batches, import_batches.c.raw_file_id == raw_files.c.id)
                .where(import_batches.c.id == batch_id)
            ).mappings().first()

    def list_records(self, current_user, report_month=None):
        with self.engine.connect() as connection:
            query = (
                select(
                    staging_records.c.id,
                    staging_records.c.import_batch_id,
                    template_definitions.c.code.label("template_code"),
                    staging_records.c.report_month,
                    staging_records.c.sheet_name,
                    staging_records.c.row_number,
                    staging_records.c.payload_json,
                    import_batches.c.committed_at.label("created_at"),
                )
                .join(import_batches, import_batches.c.id == staging_records.c.import_batch_id)
                .join(template_definitions, template_definitions.c.id == import_batches.c.template_id)
                .join(monthly_tasks, monthly_tasks.c.id == import_batches.c.task_id)
                .where(
                    import_batches.c.status == "committed",
                    import_batches.c.active_commit_key.is_not(None),
                )
                .order_by(staging_records.c.id)
            )
            if current_user["role"] != "admin":
                query = query.where(monthly_tasks.c.owner_user_id == current_user["id"])
            if report_month:
                query = query.where(staging_records.c.report_month == report_month)
            rows = connection.execute(query).mappings().all()
            payloads = [{**dict(row), "payload": json.loads(row["payload_json"])} for row in rows]
            return [self._json_ready(item) for item in payloads]

    def can_access_template_version_file(self, current_user, template_code, version):
        if current_user["role"] == "admin":
            return True
        with self.engine.connect() as connection:
            return connection.execute(
                select(monthly_tasks.c.id)
                .join(template_definitions, template_definitions.c.id == monthly_tasks.c.template_id)
                .join(template_versions, template_versions.c.id == monthly_tasks.c.template_version_id)
                .where(
                    template_definitions.c.code == template_code,
                    template_versions.c.version == version,
                    monthly_tasks.c.owner_user_id == current_user["id"],
                )
                .limit(1)
            ).first() is not None

    def list_audit_logs(self, current_user, limit=100):
        with self.engine.connect() as connection:
            rows = connection.execute(select(audit_logs).order_by(audit_logs.c.id.desc()).limit(limit)).mappings().all()
            return [self._audit_payload(connection, row) for row in rows]

    def list_data_connections(self):
        with self.engine.connect() as connection:
            rows = connection.execute(select(data_connections).order_by(data_connections.c.id.desc())).mappings().all()
            return [self._data_connection_payload(row) for row in rows]

    def get_data_connection(self, connection_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(data_connections).where(data_connections.c.id == connection_id)).mappings().first()
            return self._data_connection_payload(row) if row else None

    def create_data_connection(self, actor_id, payload):
        with self.engine.begin() as connection:
            result = connection.execute(
                insert(data_connections).values(
                    name=payload["name"],
                    connection_type=payload.get("connection_type") or "mysql",
                    host=payload["host"],
                    port=payload.get("port") or 3306,
                    username=payload["username"],
                    password_secret=encrypt_secret(payload.get("password") or ""),
                    database_name=payload.get("database_name") or None,
                    status=payload.get("status") or "active",
                    created_by_user_id=actor_id,
                    updated_at=utcnow(),
                )
            )
            connection_id = result.inserted_primary_key[0]
            self.audit(connection, actor_id, "data_connections.create", "data_connection", str(connection_id), "新增数据连接", {"name": payload["name"], "type": payload.get("connection_type") or "mysql"})
            row = connection.execute(select(data_connections).where(data_connections.c.id == connection_id)).mappings().first()
            return self._data_connection_payload(row)

    def update_data_connection(self, actor_id, connection_id, payload):
        allowed = {
            key: payload[key]
            for key in ("name", "connection_type", "host", "port", "username", "database_name", "status")
            if key in payload
        }
        if payload.get("password"):
            allowed["password_secret"] = encrypt_secret(payload["password"])
        allowed["updated_at"] = utcnow()
        with self.engine.begin() as connection:
            row = connection.execute(select(data_connections).where(data_connections.c.id == connection_id)).mappings().first()
            if not row:
                raise ValueError("数据连接不存在")
            if allowed.get("host") == self._mask_host(row["host"]):
                allowed.pop("host")
            used = connection.execute(
                select(import_batches.c.id).where(import_batches.c.target_connection_id == connection_id).limit(1)
            ).first()
            changed_fields = {
                key for key in ("connection_type", "host", "port", "username", "database_name")
                if key in allowed and allowed[key] != row[key]
            }
            if "password_secret" in allowed:
                changed_fields.add("password")
            if used:
                changed_identity = sorted(changed_fields.intersection({"host", "port", "database_name"}))
                if changed_identity:
                    raise ValueError("已用于正式批次的数据连接不能修改主机、端口或库名，请新建连接")
            if changed_fields:
                allowed.update(
                    last_test_status=None,
                    last_test_message="连接配置已修改，请重新测试",
                    last_tested_at=None,
                    server_uuid=None,
                    same_instance=False,
                )
            connection.execute(update(data_connections).where(data_connections.c.id == connection_id).values(**allowed))
            self.audit(connection, actor_id, "data_connections.update", "data_connection", str(connection_id), "更新数据连接", {"id": connection_id, "test_invalidated": bool(changed_fields), "changed_fields": sorted(changed_fields)})
            row = connection.execute(select(data_connections).where(data_connections.c.id == connection_id)).mappings().first()
            result = self._data_connection_payload(row)
        self._invalidate_mapping_metadata_cache(connection_id)
        return result

    def data_connection_deletion_impact(self, connection_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(data_connections).where(data_connections.c.id == connection_id)).mappings().first()
            if not row:
                raise ValueError("数据连接不存在")
            mappings = connection.execute(
                select(template_table_mappings.c.id, template_definitions.c.short_name, template_versions.c.version)
                .select_from(template_table_mappings.join(template_versions).join(template_definitions))
                .where(template_table_mappings.c.data_connection_id == connection_id, template_table_mappings.c.archived_at.is_(None))
            ).mappings().all()
            batch_count = connection.execute(select(func.count()).select_from(import_batches).where(import_batches.c.target_connection_id == connection_id)).scalar_one()
            operation_count = connection.execute(select(func.count()).select_from(target_write_operations).where(target_write_operations.c.data_connection_id == connection_id)).scalar_one()
            return self._json_ready({
                "connection": self._data_connection_payload(row),
                "can_delete": batch_count == 0 and operation_count == 0,
                "mapping_count": len(mappings), "batch_count": batch_count, "operation_count": operation_count,
                "affected_templates": sorted({f"{item['short_name']} v{item['version']}" for item in mappings}),
            })

    def delete_data_connection(self, actor_id, connection_id):
        impact = self.data_connection_deletion_impact(connection_id)
        if not impact["can_delete"]:
            raise ValueError("该连接已有正式批次或写入台账，不能删除；可以停用连接以保留历史恢复能力")
        with self.engine.begin() as connection:
            row = connection.execute(select(data_connections).where(data_connections.c.id == connection_id)).mappings().first()
            if not row:
                raise ValueError("数据连接不存在")
            mapping_ids = list(connection.execute(select(template_table_mappings.c.id).where(template_table_mappings.c.data_connection_id == connection_id)).scalars())
            if mapping_ids:
                ledger_count = connection.execute(select(func.count()).select_from(target_write_rows).where(target_write_rows.c.table_mapping_id.in_(mapping_ids))).scalar_one()
                if ledger_count:
                    raise ValueError("该连接映射仍被写入台账引用，不能删除")
                connection.execute(delete(template_table_mappings).where(template_table_mappings.c.id.in_(mapping_ids)))
            self.audit(connection, actor_id, "data_connections.delete", "data_connection", str(connection_id), "删除未使用数据连接及映射", {"name": row["name"], "mapping_count": len(mapping_ids)})
            connection.execute(delete(data_connections).where(data_connections.c.id == connection_id))
        self._invalidate_mapping_metadata_cache(connection_id)
        return {"id": connection_id, "deleted": True, "mapping_count": len(mapping_ids)}

    def rotate_data_connection_secrets(self, old_secret_key, actor_id=None):
        if not old_secret_key:
            raise ValueError("缺少旧密钥，不能执行凭据轮换")
        if old_secret_key == settings.secret_key:
            raise ValueError("新旧密钥不能相同")
        with self.engine.begin() as connection:
            rows = connection.execute(select(data_connections).order_by(data_connections.c.id)).mappings().all()
            rotated = []
            for row in rows:
                stored = row.get("password_secret") or ""
                if not stored:
                    continue
                plaintext = decrypt_secret_with_key(stored, old_secret_key)
                encrypted = encrypt_secret_with_key(plaintext, settings.secret_key)
                if decrypt_secret(encrypted) != plaintext:
                    raise ValueError("新密钥加密结果校验失败，已取消密钥轮换")
                rotated.append((row["id"], encrypted))
            for connection_id, encrypted in rotated:
                connection.execute(
                    update(data_connections)
                    .where(data_connections.c.id == connection_id)
                    .values(
                        password_secret=encrypted,
                        last_test_status=None,
                        last_test_message="应用密钥已轮换，请重新测试连接",
                        last_tested_at=None,
                        server_uuid=None,
                        same_instance=False,
                        updated_at=utcnow(),
                    )
                )
            self.audit(
                connection,
                actor_id,
                "data_connections.credentials_rotate",
                "data_connection",
                "all",
                "轮换数据连接加密凭据",
                {"connection_count": len(rotated)},
            )
        for connection_id, _encrypted in rotated:
            self._invalidate_mapping_metadata_cache(connection_id)
        return {"rotated_connections": len(rotated)}

    def test_data_connection(self, actor_id, connection_id):
        with self.engine.begin() as connection:
            row = connection.execute(select(data_connections).where(data_connections.c.id == connection_id)).mappings().first()
            if not row:
                raise ValueError("数据连接不存在")
            try:
                plaintext_password = decrypt_secret(row["password_secret"])
            except ValueError:
                connection.execute(
                    update(data_connections)
                    .where(data_connections.c.id == connection_id)
                    .values(
                        last_test_status="failed",
                        last_test_message="连接凭据不可用，请编辑连接并重新保存密码",
                        last_tested_at=utcnow(),
                        server_uuid=None,
                        same_instance=False,
                        updated_at=utcnow(),
                    )
                )
                self.audit(connection, actor_id, "data_connections.test", "data_connection", str(connection_id), "测试数据连接", {"id": connection_id, "status": "credential_unreadable"})
            else:
                ok, message, server_uuid, same_instance = self._probe_mysql_connection(row)
                encrypted_password = encrypt_secret(plaintext_password)
                connection.execute(
                    update(data_connections)
                    .where(data_connections.c.id == connection_id)
                    .values(
                        last_test_status="success" if ok else "failed",
                        last_test_message=message,
                        last_tested_at=utcnow(),
                        server_uuid=server_uuid,
                        same_instance=same_instance,
                        password_secret=encrypted_password,
                        updated_at=utcnow(),
                    )
                )
                self.audit(connection, actor_id, "data_connections.test", "data_connection", str(connection_id), "测试数据连接", {"id": connection_id, "status": "success" if ok else "failed"})
            row = connection.execute(select(data_connections).where(data_connections.c.id == connection_id)).mappings().first()
            result = self._data_connection_payload(row)
        self._invalidate_mapping_metadata_cache(connection_id)
        return result

    def _invalidate_mapping_metadata_cache(self, connection_id):
        with self._mapping_metadata_cache_lock:
            keys = [key for key in self._mapping_metadata_cache if key[0] == connection_id]
            for key in keys:
                self._mapping_metadata_cache.pop(key, None)

    def _mapping_metadata_cache_get(self, key):
        with self._mapping_metadata_cache_lock:
            cached = self._mapping_metadata_cache.get(key)
            if not cached:
                return None
            stored_at, value = cached
            if monotonic() - stored_at > MAPPING_METADATA_CACHE_TTL_SECONDS:
                self._mapping_metadata_cache.pop(key, None)
                return None
            return value

    def _mapping_metadata_cache_set(self, key, value):
        with self._mapping_metadata_cache_lock:
            self._mapping_metadata_cache[key] = (monotonic(), value)

    def _probe_mysql_connection(self, row):
        if row["connection_type"] != "mysql":
            return False, "首期仅支持 MySQL", None, False
        try:
            self._validate_target_schema(row.get("database_name"))
            self._validate_target_host(row)
        except ValueError as exc:
            return False, str(exc), None, False
        try:
            engine = self._mysql_engine_for_row(row)
            with engine.connect() as probe:
                target_uuid = probe.execute(text("SELECT @@server_uuid")).scalar_one()
            app_uuid = self._app_server_uuid()
            same_instance = bool(app_uuid and target_uuid == app_uuid)
            message = "连接成功，与应用数据库属于同一实例" if same_instance else "连接成功，可用作独立目标数据库"
            return True, message, target_uuid, same_instance
        except OperationalError as exc:
            code = exc.orig.args[0] if getattr(exc, "orig", None) and exc.orig.args else None
            if code == 1045:
                return False, "账号或密码不正确", None, False
            if code == 1049:
                return False, "库名不存在或当前账号无权访问", None, False
            if code == 2003:
                return False, "无法连接到服务器，请检查地址、端口和网络权限", None, False
            return False, "连接失败，请检查配置和网络权限", None, False
        except Exception:
            return False, "连接测试失败，请检查配置", None, False

    def _mysql_engine_for_row(self, row):
        database_name = row["database_name"] or ""
        db_part = f"/{quote_plus(database_name)}" if database_name else ""
        url = (
            "mysql+pymysql://"
            f"{quote_plus(row['username'])}:{quote_plus(decrypt_secret(row['password_secret']))}"
            f"@{row['host']}:{row['port']}{db_part}?charset=utf8mb4"
        )
        return create_engine(url, future=True, pool_pre_ping=True, connect_args={"connect_timeout": 5})

    def _app_server_uuid(self):
        if self.dialect != "mysql":
            return None
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT @@server_uuid")).scalar_one()

    def _mapping_connection_row(self, connection_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(data_connections).where(data_connections.c.id == connection_id)).mappings().first()
        if not row:
            raise ValueError("数据连接不存在")
        if row["status"] != "active" or row["last_test_status"] != "success":
            raise ValueError("请先测试并确认该目标数据库连接可用")
        if self._connection_credential_status(row) != "ready":
            raise ValueError("数据连接凭据不可用，请先编辑连接并重新保存密码")
        schema = row["database_name"]
        if not schema:
            raise ValueError("请先配置目标库名")
        self._validate_target_schema(schema)
        return row, schema

    def _validate_target_schema(self, schema):
        schema = str(schema or "").strip()
        if not schema:
            raise ValueError("目标库名不能为空")
        application_schema = make_url(self.database_url).database
        if self.dialect == "mysql" and schema == application_schema:
            raise ValueError("业务目标表必须位于应用库之外的受控数据库")
        return schema

    def _validate_target_host(self, row):
        host = str(row.get("host") or "").strip().lower()
        port = int(row.get("port") or 3306)
        if not host:
            raise ValueError("目标数据库主机不能为空")
        return host, port

    def _ensure_external_write_allowed(self, row):
        if settings.environment in {"development", "production"}:
            if not settings.external_writes_enabled:
                raise ValueError(f"{'开发' if settings.environment == 'development' else '生产'}环境外部写入未启用")
            if row.get("status") != "active" or row.get("last_test_status") != "success":
                raise ValueError("仅允许写入管理员已启用且测试成功的数据连接")
            if self._connection_credential_status(row) != "ready":
                raise ValueError("数据连接凭据不可用，请先编辑连接并重新保存密码")
        if settings.environment == "development":
            application_url = make_url(self.database_url)
            if application_url.drivername.startswith("sqlite"):
                database_path = str(application_url.database or "")
                resolved = Path(database_path).expanduser().resolve() if database_path and database_path != ":memory:" else None
                volatile_roots = tuple(Path(item).resolve() for item in ("/tmp", "/private/tmp", "/var/tmp", "/private/var/folders"))
                if resolved is None or any(resolved == root or resolved.is_relative_to(root) for root in volatile_roots):
                    raise ValueError("开发环境外部写入禁止使用临时 SQLite 应用库，请配置持久应用库并保留完整写入台账")
        self._validate_target_host(row)
        self._validate_target_schema(row.get("database_name"))
        if settings.environment in {"development", "production"}:
            return True
        application_database = str(make_url(self.database_url).database or "")
        target_database = str(row.get("database_name") or "")
        if not settings.test_external_writes_enabled or not application_database.endswith("_test") or not target_database.endswith("_test"):
            raise ValueError("自动化测试环境仅允许显式启用的 _test MySQL 外部写入")
        return True

    def list_connection_tables(self, connection_id, refresh=False):
        row, schema = self._mapping_connection_row(connection_id)
        cache_key = (connection_id, "tables", schema)
        target_engine = self._mysql_engine_for_row(row)
        with target_engine.connect() as target:
            names = inspect(target).get_table_names()
        result = sorted(names)
        self._mapping_metadata_cache_set(cache_key, tuple(result))
        return result

    def get_connection_table_columns(self, connection_id, table_name, refresh=False):
        row, schema = self._mapping_connection_row(connection_id)
        cache_key = (connection_id, "columns", schema, table_name)
        cached = None if refresh else self._mapping_metadata_cache_get(cache_key)
        if cached is not None:
            return [dict(item) for item in cached]
        target_engine = self._mysql_engine_for_row(row)
        with target_engine.connect() as target:
            inspector = inspect(target)
            if not inspector.has_table(table_name):
                raise ValueError("目标表不存在或不允许映射")
            primary_keys = set((inspector.get_pk_constraint(table_name) or {}).get("constrained_columns") or [])
            columns = inspector.get_columns(table_name)
        result = [
            {
                "name": item["name"],
                "type": str(item["type"]),
                "nullable": bool(item.get("nullable")),
                "default": item.get("default"),
                "primary_key": item["name"] in primary_keys,
                "autoincrement": item.get("autoincrement") is True,
            }
            for item in columns
        ]
        self._mapping_metadata_cache_set(cache_key, tuple(dict(item) for item in result))
        return result

    def _mapping_validation_details(self, mapping, data_connection, source_fields, refresh=False):
        errors = []
        columns = []
        if not data_connection or data_connection["status"] != "active" or data_connection["last_test_status"] != "success":
            errors.append("目标数据库连接未启用或尚未测试成功")
        elif self._connection_credential_status(data_connection) != "ready":
            errors.append("目标数据库连接凭据不可用，请管理员重新保存密码")
        else:
            try:
                self._validate_target_host(data_connection)
                self._validate_target_schema(data_connection.get("database_name"))
                columns = self.get_connection_table_columns(
                    data_connection["id"], mapping["target_table"], refresh=refresh
                )
            except ValueError as exc:
                errors.append(str(exc))
        column_names = {item["name"] for item in columns}
        primary_keys = [item["name"] for item in columns if item["primary_key"]]
        field_mapping = json.loads(mapping.get("field_mapping_json") or "{}")
        mapped_fields = [field_mapping.get(field, field) for field in source_fields]
        missing_fields = [field for field in mapped_fields if field not in column_names]
        system_fields = [
            "report_month",
            "import_batch_id",
            "source_sheet_name",
            "source_row_number",
            "data_import_time",
            "data_import_user",
        ]
        missing_system_fields = [field for field in system_fields if field not in column_names]
        required_target = [
            item["name"]
            for item in columns
            if not item["nullable"]
            and item["default"] is None
            and not item["autoincrement"]
            and item["name"] not in mapped_fields + system_fields
        ]
        if columns and not primary_keys:
            errors.append("目标表必须配置主键")
        if columns and missing_fields:
            errors.append(f"目标表缺少字段：{'、'.join(missing_fields)}")
        if columns and missing_system_fields:
            errors.append(f"目标表缺少系统字段：{'、'.join(missing_system_fields)}")
        if columns and required_target:
            errors.append(f"目标表存在文件无法提供的必填列：{'、'.join(required_target)}")
        return {
            "valid": not errors,
            "errors": errors,
            "source_fields": source_fields,
            "field_mapping": field_mapping,
            "primary_keys": primary_keys,
            "columns": columns,
        }

    def list_template_mappings(self):
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(template_table_mappings)
                .select_from(template_table_mappings.join(template_versions).join(template_definitions))
                .where(template_table_mappings.c.archived_at.is_(None), template_definitions.c.archived_at.is_(None))
                .order_by(template_table_mappings.c.id.desc())
            ).mappings().all()
            return [self._mapping_payload(connection, row) for row in rows]

    def get_template_mapping(self, template_code, version=None, source_sheet_name=None):
        with self.engine.connect() as connection:
            template = connection.execute(
                select(template_definitions).where(template_definitions.c.code == template_code)
            ).mappings().first()
            if not template:
                return None
            query = select(template_versions).where(template_versions.c.template_id == template["id"])
            if version:
                query = query.where(template_versions.c.version == version)
            else:
                query = query.order_by(template_versions.c.effective_month.desc(), template_versions.c.id.desc()).limit(1)
            version_row = connection.execute(query).mappings().first()
            if not version_row:
                return None
            mapping_query = select(template_table_mappings).where(
                template_table_mappings.c.template_version_id == version_row["id"],
                template_table_mappings.c.is_active.is_(True),
                template_table_mappings.c.archived_at.is_(None),
            )
            if source_sheet_name:
                mapping_query = mapping_query.where(template_table_mappings.c.source_sheet_name == source_sheet_name)
            mapping = connection.execute(mapping_query.order_by(template_table_mappings.c.id.desc())).mappings().first()
            return self._mapping_payload(connection, mapping) if mapping else None

    def save_template_mapping(self, actor_id, template_code, version, connection_id, target_table, source_fields, field_mapping=None, source_sheet_name=None):
        with self.engine.begin() as connection:
            template = connection.execute(
                select(template_definitions).where(template_definitions.c.code == template_code)
            ).mappings().first()
            if not template:
                raise ValueError("模板不存在")
            version_row = connection.execute(
                select(template_versions).where(
                    template_versions.c.template_id == template["id"],
                    template_versions.c.version == version,
                )
            ).mappings().first()
            if not version_row:
                raise ValueError("模板版本不存在")
            correction_state = self._template_mapping_correction_state(connection, version_row["id"])
            analysis = json.loads(version_row.get("template_file_analysis_json") or "{}")
            sheets = [item for item in analysis.get("sheets") or [] if item.get("name")]
            if not source_sheet_name:
                if len(sheets) != 1:
                    raise ValueError("多工作表模板必须指定工作表")
                source_sheet_name = sheets[0]["name"]
            if source_sheet_name not in {item["name"] for item in sheets}:
                raise ValueError("模板版本中不存在该工作表")
            data_connection = connection.execute(
                select(data_connections).where(data_connections.c.id == connection_id)
            ).mappings().first()
            if not data_connection:
                raise ValueError("数据连接不存在")
            self._validate_target_schema(data_connection["database_name"])
            sibling_mappings = connection.execute(
                select(template_table_mappings).where(
                    template_table_mappings.c.template_version_id == version_row["id"],
                    template_table_mappings.c.archived_at.is_(None),
                )
            ).mappings().all()
            if any(
                item["data_connection_id"] != connection_id
                for item in sibling_mappings
                if item.get("is_active") and item.get("source_sheet_name") != source_sheet_name
            ):
                raise ValueError("同一模板的所有工作表必须使用同一个数据连接")
            target_schema = data_connection["database_name"] or ""
            exact_candidates = [
                item for item in sibling_mappings
                if (item.get("source_sheet_name") == source_sheet_name or (len(sheets) == 1 and not item.get("source_sheet_name")))
                and item["data_connection_id"] == connection_id
                and item["target_schema"] == target_schema
                and item["target_table"] == target_table
            ]
            existing = next((item for item in exact_candidates if item.get("source_sheet_name") == source_sheet_name), None)
            existing = existing or (exact_candidates[0] if exact_candidates else None)
            requested_field_mapping_json = json.dumps(field_mapping or {}, ensure_ascii=False, sort_keys=True)
            usage_months = self._mapping_usage_months(connection, version_row["id"], existing["id"]) if existing else []
            if existing and usage_months:
                stored_field_mapping_json = json.dumps(json.loads(existing.get("field_mapping_json") or "{}"), ensure_ascii=False, sort_keys=True)
                if stored_field_mapping_json != requested_field_mapping_json:
                    raise ValueError(
                        f"该目标映射已用于目标库写入（{', '.join(usage_months)}），不能修改字段映射；"
                        "可以直接切换回该目标，或选择其他连接和目标表新增候选目标"
                    )
            connection.execute(
                update(template_table_mappings)
                .where(
                    template_table_mappings.c.template_version_id == version_row["id"],
                    template_table_mappings.c.source_sheet_name == source_sheet_name,
                )
                .values(is_active=False, updated_at=utcnow())
            )
            if len(sheets) == 1:
                connection.execute(
                    update(template_table_mappings)
                    .where(
                        template_table_mappings.c.template_version_id == version_row["id"],
                        template_table_mappings.c.source_sheet_name.is_(None),
                    )
                    .values(is_active=False, updated_at=utcnow())
                )
            values = {
                "template_version_id": version_row["id"],
                "source_sheet_name": source_sheet_name,
                "data_connection_id": connection_id,
                "target_schema": target_schema,
                "target_table": target_table,
                "is_active": True,
                "field_mapping_json": requested_field_mapping_json,
                "status": "draft",
                "last_validation_json": "{}",
                "last_validated_at": None,
                "created_by_user_id": actor_id,
                "updated_at": utcnow(),
            }
            if existing:
                if usage_months:
                    connection.execute(
                        update(template_table_mappings)
                        .where(template_table_mappings.c.id == existing["id"])
                        .values(is_active=True, source_sheet_name=source_sheet_name, updated_at=utcnow())
                    )
                else:
                    connection.execute(update(template_table_mappings).where(template_table_mappings.c.id == existing["id"]).values(**values))
                mapping_id = existing["id"]
            else:
                result = connection.execute(insert(template_table_mappings).values(**values))
                mapping_id = result.inserted_primary_key[0]
            self.audit(
                connection,
                actor_id,
                "mappings.activate" if usage_months else "templates.version_correct" if correction_state["task_count"] else "mappings.save",
                "template_mapping",
                str(mapping_id),
                "切换当前目标映射" if usage_months else "无批次纠正模板映射" if correction_state["task_count"] else "保存模板入库映射",
                {"template_code": template_code, "version": version, "source_sheet_name": source_sheet_name, "target_schema": target_schema, "target_table": target_table, "activation": bool(usage_months)},
            )
        if usage_months:
            with self.engine.connect() as connection:
                mapping = connection.execute(select(template_table_mappings).where(template_table_mappings.c.id == mapping_id)).mappings().first()
                return self._mapping_payload(connection, mapping)
        return self.validate_template_mapping(actor_id, mapping_id, source_fields)

    def delete_template_mapping(self, actor_id, mapping_id):
        with self.engine.begin() as connection:
            mapping = connection.execute(select(template_table_mappings).where(template_table_mappings.c.id == mapping_id)).mappings().first()
            if not mapping:
                raise ValueError("模板映射不存在")
            if mapping.get("archived_at"):
                raise ValueError("模板映射已经解除")
            usage_months = self._mapping_usage_months(connection, mapping["template_version_id"], mapping_id)
            ledger_count = connection.execute(select(func.count()).select_from(target_write_rows).where(target_write_rows.c.table_mapping_id == mapping_id)).scalar_one()
            if usage_months or ledger_count:
                connection.execute(update(template_table_mappings).where(template_table_mappings.c.id == mapping_id).values(
                    archived_at=utcnow(), is_active=False, status="archived", updated_at=utcnow()
                ))
                mode = "archive"
            else:
                connection.execute(delete(template_table_mappings).where(template_table_mappings.c.id == mapping_id))
                mode = "delete"
            self.audit(connection, actor_id, "mappings.remove", "template_mapping", str(mapping_id), "解除模板目标映射", {"mode": mode, "usage_months": usage_months})
            return {"id": mapping_id, "mode": mode, "usage_months": usage_months}

    def validate_template_mapping(self, actor_id, mapping_id, source_fields):
        with self.engine.connect() as connection:
            mapping = connection.execute(select(template_table_mappings).where(template_table_mappings.c.id == mapping_id)).mappings().first()
            data_connection = connection.execute(select(data_connections).where(data_connections.c.id == mapping["data_connection_id"])).mappings().first() if mapping else None
        if not mapping or not data_connection:
            raise ValueError("模板映射不存在")
        validation = self._mapping_validation_details(mapping, data_connection, source_fields, refresh=True)
        errors = validation["errors"]
        with self.engine.begin() as connection:
            connection.execute(
                update(template_table_mappings)
                .where(template_table_mappings.c.id == mapping_id)
                .values(
                    status="enabled" if not errors else "invalid",
                    last_validation_json=json.dumps(validation, ensure_ascii=False, default=str),
                    last_validated_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            self.audit(connection, actor_id, "mappings.validate", "template_mapping", str(mapping_id), "校验模板入库映射", {"valid": not errors})
            row = connection.execute(select(template_table_mappings).where(template_table_mappings.c.id == mapping_id)).mappings().first()
            return self._mapping_payload(connection, row)

    def audit(self, connection, actor_id, action, target_type, target_id, message, payload):
        connection.execute(
            insert(audit_logs).values(
                actor_user_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=str(target_id),
                message=message,
                payload_json=json.dumps(payload or {}, ensure_ascii=False, default=str),
            )
        )

    def _insert_errors(self, connection, batch_id, errors):
        if not errors:
            return
        connection.execute(
            insert(validation_errors),
            [
                {
                    "import_batch_id": batch_id,
                    "row_number": error.get("row_number"),
                    "cell": error.get("cell"),
                    "field": error.get("field"),
                    "code": error["code"],
                    "message": error["message"],
                    "suggestion": error["suggestion"],
                    "blocking": bool(error.get("blocking")),
                }
                for error in errors
            ],
        )

    def _insert_staging(self, connection, batch_id, records):
        connection.execute(
            insert(staging_records),
            [
                {
                    "import_batch_id": batch_id,
                    "report_month": record["report_month"],
                    "sheet_name": record["sheet_name"],
                    "row_number": record["row_number"],
                    "payload_json": json.dumps(record["payload"], ensure_ascii=False, default=str),
                }
                for record in records
            ],
        )

    def _version_for_month(self, connection, template_id, report_month):
        return connection.execute(
            select(template_versions)
            .where(template_versions.c.template_id == template_id, template_versions.c.effective_month <= report_month)
            .order_by(template_versions.c.effective_month.desc(), template_versions.c.id.desc())
            .limit(1)
        ).mappings().first()

    def _owner_for_month(self, connection, template_id, report_month):
        row = connection.execute(
            select(responsibilities.c.owner_user_id)
            .where(responsibilities.c.template_id == template_id, responsibilities.c.effective_month <= report_month)
            .order_by(responsibilities.c.effective_month.desc(), responsibilities.c.id.desc())
            .limit(1)
        ).first()
        return row[0] if row else None

    def _user_by_id(self, connection, user_id):
        if not user_id:
            return None
        row = connection.execute(select(users).where(users.c.id == user_id)).mappings().first()
        return self.public_user(row) if row else None

    def _template_payload(self, connection, row, version=None, report_month=None):
        if not row:
            return None
        version_query = select(template_versions).where(template_versions.c.template_id == row["id"])
        if version:
            version_query = version_query.where(template_versions.c.version == version)
        elif report_month:
            version_query = version_query.where(template_versions.c.effective_month <= report_month).order_by(
                template_versions.c.effective_month.desc(), template_versions.c.id.desc()
            ).limit(1)
        else:
            version_query = version_query.order_by(
                template_versions.c.effective_month.desc(), template_versions.c.id.desc()
            ).limit(1)
        latest = connection.execute(version_query).mappings().first()
        if version and not latest:
            return None
        payload = dict(row)
        if latest:
            payload["version"] = latest["version"]
            payload["effective_month"] = latest["effective_month"]
            payload["sample_filename"] = latest["sample_filename"]
            payload["match"] = json.loads(latest["match_json"])
            payload["header_keywords"] = json.loads(latest["header_keywords_json"])
            payload["date_fields"] = json.loads(latest["date_fields_json"])
            payload["required_fields"] = json.loads(latest["required_fields_json"])
            payload["numeric_fields"] = json.loads(latest["numeric_fields_json"])
            payload["validation_rules"] = json.loads(latest["validation_rules_json"] or "[]")
            payload["template_file"] = self._template_file_payload(latest)
            mappings = connection.execute(
                select(template_table_mappings).where(
                    template_table_mappings.c.template_version_id == latest["id"],
                    template_table_mappings.c.archived_at.is_(None),
                )
            ).mappings().all()
            mappings = sorted(mappings, key=lambda item: (not bool(item.get("is_active")), item["id"]))
            payload["table_mappings"] = [self._mapping_payload(connection, mapping) for mapping in mappings]
            payload["table_mapping"] = next((item for item in payload["table_mappings"] if item.get("is_active")), None)
        else:
            payload.update(describe_template(TEMPLATES[0]))
            payload["table_mapping"] = None
            payload["table_mappings"] = []
        sheet_names = [item.get("name") for item in ((payload.get("template_file") or {}).get("analysis") or {}).get("sheets", []) if item.get("name")]
        enabled_sheets = {item.get("source_sheet_name") for item in payload["table_mappings"] if item.get("is_active") and item.get("status") == "enabled"}
        payload["target_strategy"] = "mapped_table" if sheet_names and (set(sheet_names) <= enabled_sheets or (len(sheet_names) == 1 and any(item.get("is_active") and item.get("status") == "enabled" for item in payload["table_mappings"]))) else "unconfigured"
        effective_month = report_month or payload.get("effective_month") or "9999-12"
        payload["owner"] = self._user_by_id(connection, self._owner_for_month(connection, row["id"], effective_month))
        return self._json_ready(payload)

    def _template_file_payload(self, version):
        if not version or not version.get("template_file_path"):
            return None
        return {
            "original_filename": version["template_file_original_name"],
            "sha256": version["template_file_sha256"],
            "size_bytes": version["template_file_size_bytes"],
            "uploaded_at": version["template_file_uploaded_at"],
            "analysis": json.loads(version["template_file_analysis_json"] or "{}"),
        }

    def _responsibility_payload(self, connection, row):
        return self._json_ready(
            {
                "id": row["id"],
                "template": {"code": row["code"], "short_name": row["short_name"]},
                "owner": self._user_by_id(connection, row["owner_user_id"]),
                "effective_month": row["effective_month"],
                "created_at": row["created_at"],
            }
        )

    def _task_payload(self, connection, row):
        owner = self._user_by_id(connection, row["owner_user_id"])
        access = self._task_access(connection, row)
        batch = None
        if row["current_batch_id"]:
            batch_row = connection.execute(
                select(import_batches).where(import_batches.c.id == row["current_batch_id"])
            ).mappings().first()
            batch = self._batch_summary(connection, batch_row) if batch_row else None
        return self._json_ready(
            {
                "id": row["id"],
                "report_month": row["report_month"],
                "status": row["status"],
                "access": access,
                "owner": owner,
                "template": {
                    "code": row["code"],
                    "name": row["name"],
                    "short_name": row["short_name"],
                    "description": row["description"],
                    "version": connection.execute(
                        select(template_versions.c.version).where(template_versions.c.id == row["template_version_id"])
                    ).scalar_one(),
                },
                "current_batch": batch,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )

    def _data_connection_payload(self, row):
        if not row:
            return None
        payload = dict(row)
        payload.pop("password_secret", None)
        payload.pop("server_uuid", None)
        payload["host"] = self._mask_host(row["host"])
        payload["password_configured"] = bool(row["password_secret"])
        credential_status = self._connection_credential_status(row)
        payload["credential_status"] = credential_status
        payload["requires_password_reset"] = credential_status == "unreadable"
        payload["write_capable"] = row["status"] == "active" and row["last_test_status"] == "success" and credential_status == "ready"
        return self._json_ready(payload)

    @staticmethod
    def _connection_credential_status(row):
        if not row or not row.get("password_secret"):
            return "missing"
        try:
            decrypt_secret(row["password_secret"])
            return "ready"
        except ValueError:
            return "unreadable"

    @staticmethod
    def _mask_host(host):
        parts = str(host).split(".")
        if len(parts) == 4 and all(part.isdigit() for part in parts):
            return f"{parts[0]}.***.***.{parts[-1]}"
        if len(parts) >= 3:
            return f"{parts[0][:3]}***.{'.'.join(parts[-2:])}"
        return f"{str(host)[:3]}***"

    def _mapping_payload(self, connection, row):
        if not row:
            return None
        version = connection.execute(
            select(template_versions).where(template_versions.c.id == row["template_version_id"])
        ).mappings().first()
        template = connection.execute(
            select(template_definitions).where(template_definitions.c.id == version["template_id"])
        ).mappings().first()
        data_connection = connection.execute(
            select(data_connections).where(data_connections.c.id == row["data_connection_id"])
        ).mappings().first()
        return self._mapping_payload_from_rows(row, version, template, data_connection)

    def _mapping_payload_from_rows(self, row, version, template, data_connection):
        return self._json_ready(
            {
                **dict(row),
                "validation": json.loads(row["last_validation_json"] or "{}"),
                "field_mapping": json.loads(row.get("field_mapping_json") or "{}"),
                "template": {
                    "code": template["code"],
                    "short_name": template["short_name"],
                    "version": version["version"],
                    "effective_month": version["effective_month"],
                },
                "connection": {
                    "id": data_connection["id"],
                    "name": data_connection["name"],
                    "same_instance": bool(data_connection["same_instance"]),
                    "write_capable": data_connection["status"] == "active" and data_connection["last_test_status"] == "success" and self._connection_credential_status(data_connection) == "ready",
                },
            }
        )

    def _batch_summary(self, connection, row):
        if not row:
            return None
        readiness = self._batch_commit_readiness(connection, row)
        return {
            "id": row["id"],
            "report_month": row["report_month"],
            "status": row["status"],
            "summary": {key: value for key, value in json.loads(row["summary_json"]).items() if not key.startswith("_")},
            "created_at": row["created_at"],
            "committed_at": row["committed_at"],
            "voided_at": row["voided_at"],
            "void_reason": row["void_reason"],
            "target_write_count": row["target_write_count"],
            "commit_readiness": readiness,
        }

    def _batch_commit_readiness(self, connection, row):
        readiness = self._template_version_commit_readiness(
            connection, row["template_version_id"], live_validate=False
        )
        summary = json.loads(row["summary_json"])
        previous = connection.execute(
            select(import_batches.c.id, import_batches.c.target_write_count)
            .where(
                import_batches.c.template_id == row["template_id"],
                import_batches.c.report_month == row["report_month"],
                import_batches.c.id != row["id"],
                import_batches.c.status == "committed",
                import_batches.c.active_commit_key.is_not(None),
            )
            .order_by(import_batches.c.committed_at.desc(), import_batches.c.id.desc())
            .limit(1)
        ).mappings().first()
        readiness["write_row_count"] = int(summary.get("valid_rows") or summary.get("total_rows") or 0)
        readiness["replace_row_count"] = int(previous["target_write_count"] or 0) if previous else 0
        readiness["replaced_batch_id"] = previous["id"] if previous else None
        return readiness

    def _batch_payload(self, connection, row):
        template = connection.execute(
            select(template_definitions).where(template_definitions.c.id == row["template_id"])
        ).mappings().first()
        raw = connection.execute(select(raw_files).where(raw_files.c.id == row["raw_file_id"])).mappings().first()
        task = (
            connection.execute(select(monthly_tasks).where(monthly_tasks.c.id == row["task_id"])).mappings().first()
            if row["task_id"]
            else None
        )
        errors = connection.execute(
            select(validation_errors).where(validation_errors.c.import_batch_id == row["id"]).order_by(validation_errors.c.id)
            .limit(50)
        ).mappings().all()
        write_operation = connection.execute(
            select(target_write_operations)
            .where(target_write_operations.c.batch_id == row["id"])
            .order_by(target_write_operations.c.id.desc())
            .limit(1)
        ).mappings().first()
        target_snapshots = json.loads(row.get("target_mappings_json") or "[]")
        mapping_ids = [item.get("mapping_id") for item in target_snapshots if item.get("mapping_id")]
        batch_mappings = [
            self._mapping_payload(connection, mapping_row)
            for mapping_row in connection.execute(
                select(template_table_mappings).where(template_table_mappings.c.id.in_(mapping_ids))
            ).mappings().all()
        ] if mapping_ids else []
        payload = {
            **dict(row),
            "summary": {key: value for key, value in json.loads(row["summary_json"]).items() if not key.startswith("_")},
            "template": {
                "code": template["code"],
                "name": template["name"],
                "short_name": template["short_name"],
            },
            "raw_file": {
                "id": raw["id"],
                "original_filename": raw["original_filename"],
                "sha256": raw["sha256"],
                "size_bytes": raw["size_bytes"],
            },
            "owner": self._user_by_id(connection, task["owner_user_id"]) if task else None,
            "access": self._task_access(connection, task) if task else None,
            "voided_by": self._user_by_id(connection, row["voided_by_user_id"]),
            "table_mapping": self._mapping_payload(
                connection,
                connection.execute(
                    select(template_table_mappings).where(template_table_mappings.c.id == row["table_mapping_id"])
                ).mappings().first(),
            ) if row["table_mapping_id"] else None,
            "table_mappings": batch_mappings,
            "errors": [dict(error) for error in errors],
            "write_operation": self._json_ready({
                "id": write_operation["id"],
                "operation_type": write_operation["operation_type"],
                "state": write_operation["state"],
                "attempt_count": write_operation["attempt_count"],
                "last_error": write_operation["last_error"],
            }) if write_operation else None,
            "commit_readiness": self._batch_commit_readiness(connection, row),
        }
        payload.pop("summary_json", None)
        payload.pop("active_commit_key", None)
        payload.pop("target_field_mapping_json", None)
        payload.pop("target_mappings_json", None)
        return self._json_ready(payload)

    def _audit_payload(self, connection, row):
        return self._json_ready(
            {
                "id": row["id"],
                "actor": self._user_by_id(connection, row["actor_user_id"]),
                "action": row["action"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "message": row["message"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
        )

    def public_user(self, row):
        if not row:
            return None
        return self._json_ready(
            {
                "id": row["id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "role": row["role"],
                "department": row["department"],
                "must_change_password": bool(row["must_change_password"]),
                "disabled": bool(row["disabled"]),
                "archived_at": row.get("archived_at"),
                "is_archived": bool(row.get("archived_at")),
            }
        )

    def _json_ready(self, payload):
        if isinstance(payload, dict):
            return {key: self._json_ready(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._json_ready(item) for item in payload]
        if isinstance(payload, datetime):
            return payload.isoformat()
        return payload
