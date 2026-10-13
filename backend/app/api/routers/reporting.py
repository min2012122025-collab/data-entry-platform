"""Reporting period and monthly-task endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ...container import database, service
from ..dependencies import active_user, admin_user
from ..schemas import ReportingDeadlineRequest


router = APIRouter(tags=["reporting periods and tasks"])


@router.post("/api/tasks/generate")
def generate_tasks(report_month: str, user=Depends(admin_user)):
    try:
        database.generate_tasks(report_month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return database.list_tasks(user, report_month)


@router.get("/api/tasks")
def list_tasks(report_month: Optional[str] = None, user=Depends(active_user)):
    return database.list_tasks(user, report_month)


@router.get("/api/task-months")
def list_task_months(user=Depends(active_user)):
    return database.list_task_months(user)


@router.get("/api/reporting-context")
def reporting_context(user=Depends(active_user)):
    return database.get_reporting_context(user)


@router.get("/api/reporting-periods")
def reporting_periods(user=Depends(admin_user)):
    return database.list_reporting_periods()


@router.get("/api/reporting-periods/{report_month}/readiness")
def reporting_period_readiness(report_month: str, user=Depends(admin_user)):
    try:
        return database.get_reporting_period_readiness(report_month, live_validate=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/reporting-periods/{report_month}/issue")
def issue_reporting_period(report_month: str, payload: ReportingDeadlineRequest, user=Depends(admin_user)):
    try:
        return database.issue_reporting_period(user["id"], report_month, payload.closes_at)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/reporting-periods/{report_month}/sync-tasks")
def sync_reporting_tasks(report_month: str, user=Depends(admin_user)):
    try:
        return database.sync_reporting_tasks(user["id"], report_month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/reporting-periods/{report_month}/deadline")
def update_reporting_deadline(report_month: str, payload: ReportingDeadlineRequest, user=Depends(admin_user)):
    try:
        return database.update_reporting_deadline(user["id"], report_month, payload.closes_at)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/reporting-periods/{report_month}/close")
def close_reporting_period(report_month: str, user=Depends(admin_user)):
    try:
        return database.close_reporting_period(user["id"], report_month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/tasks/{task_id}/reopen")
def reopen_reporting_task(task_id: int, payload: ReportingDeadlineRequest, user=Depends(admin_user)):
    try:
        return database.reopen_task(user["id"], task_id, payload.closes_at)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/tasks/{task_id}/close-reopen")
def close_reopened_task(task_id: int, user=Depends(admin_user)):
    try:
        return database.close_reopened_task(user["id"], task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/tasks/{task_id}/not-required")
def mark_task_not_required(task_id: int, user=Depends(admin_user)):
    try:
        return database.mark_task_not_required(user["id"], task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/tasks/{task_id}/restore-required")
def restore_required_task(task_id: int, user=Depends(admin_user)):
    try:
        return database.restore_required_task(user["id"], task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/tasks/{task_id}")
def get_task(task_id: int, user=Depends(active_user)):
    task = database.get_task(user, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/api/tasks/{task_id}/template-file")
def download_task_template_file(task_id: int, user=Depends(active_user)):
    task = database.get_task(user, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        path, filename = service.get_template_file(task["template"]["code"], task["template"]["version"], blank=True)
        return FileResponse(path, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
