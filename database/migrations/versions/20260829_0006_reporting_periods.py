"""add reporting periods and task reopen windows

Revision ID: 20260829_0006
Revises: 20260825_0005
Create Date: 2026-08-29
"""

from calendar import monthrange
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op


revision = "20260829_0006"
down_revision = "20260825_0005"
branch_labels = None
depends_on = None

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _previous_month(now):
    year, month = now.year, now.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year:04d}-{month:02d}"


def _deadline(report_month):
    year, month = (int(part) for part in report_month.split("-"))
    next_year, next_month = year, month + 1
    if next_month == 13:
        next_year, next_month = year + 1, 1
    local = datetime(
        next_year,
        next_month,
        monthrange(next_year, next_month)[1],
        23,
        59,
        59,
        tzinfo=SHANGHAI_TZ,
    )
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "reporting_periods" not in inspector.get_table_names():
        op.create_table(
            "reporting_periods",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("report_month", sa.String(length=7), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
            sa.Column("issued_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("issued_at", sa.DateTime(), nullable=True),
            sa.Column("closes_at", sa.DateTime(), nullable=True),
            sa.Column("closed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("report_month", name="uq_reporting_period_month"),
        )
    task_columns = {item["name"] for item in sa.inspect(bind).get_columns("monthly_tasks")}
    missing_columns = [name for name in ("reopened_until", "reopened_by_user_id", "reopened_at") if name not in task_columns]
    if missing_columns:
        with op.batch_alter_table("monthly_tasks") as batch:
            if "reopened_until" in missing_columns:
                batch.add_column(sa.Column("reopened_until", sa.DateTime(), nullable=True))
            if "reopened_by_user_id" in missing_columns:
                batch.add_column(sa.Column("reopened_by_user_id", sa.Integer(), nullable=True))
                batch.create_foreign_key("fk_task_reopened_by_user", "users", ["reopened_by_user_id"], ["id"])
            if "reopened_at" in missing_columns:
                batch.add_column(sa.Column("reopened_at", sa.DateTime(), nullable=True))

    now_local = datetime.now(SHANGHAI_TZ)
    now_utc = now_local.astimezone(timezone.utc).replace(tzinfo=None)
    previous = _previous_month(now_local)
    admin_id = bind.execute(sa.text("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")).scalar()
    months = bind.execute(sa.text("SELECT DISTINCT report_month FROM monthly_tasks ORDER BY report_month")).scalars().all()
    existing_months = set(bind.execute(sa.text("SELECT report_month FROM reporting_periods")).scalars())
    for report_month in months:
        if report_month in existing_months:
            continue
        issued = report_month <= previous
        bind.execute(
            sa.text(
                "INSERT INTO reporting_periods "
                "(report_month, status, issued_by_user_id, issued_at, closes_at, created_at, updated_at) "
                "VALUES (:report_month, :status, :actor, :issued_at, :closes_at, :now, :now)"
            ),
            {
                "report_month": report_month,
                "status": "issued" if issued else "draft",
                "actor": admin_id if issued else None,
                "issued_at": now_utc if issued else None,
                "closes_at": _deadline(report_month) if issued else None,
                "now": now_utc,
            },
        )


def downgrade():
    with op.batch_alter_table("monthly_tasks") as batch:
        batch.drop_constraint("fk_task_reopened_by_user", type_="foreignkey")
        batch.drop_column("reopened_at")
        batch.drop_column("reopened_by_user_id")
        batch.drop_column("reopened_until")
    op.drop_table("reporting_periods")
