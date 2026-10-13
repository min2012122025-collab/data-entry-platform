"""Workbook upload, validation, import history, commit, void, and records endpoints."""

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse

from ...container import database, service
from ...core.config import settings
from ..dependencies import active_user, admin_user
from ..schemas import CommitRequest, VoidRequest

router = APIRouter(tags=["imports and history"])
MAX_WORKBOOK_SIZE_BYTES = 20 * 1024 * 1024


@router.get("/api/source-files")
def list_source_files(user=Depends(admin_user)):
    return service.list_source_files()


@router.get("/api/source-files/{filename}")
def download_source_file(filename: str, user=Depends(admin_user)):
    path = settings.source_dir / Path(filename).name
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=path.name)


@router.post("/api/source-imports")
def import_source_file(filename: str, user=Depends(admin_user)):
    try:
        return service.import_source_file(user, filename)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/imports")
async def create_import(template_code: str, report_month: str = Query(..., pattern=r"^\d{4}-\d{2}$"), file: UploadFile = File(...), user=Depends(active_user)):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx 或 .xlsm 文件")
    try:
        database.require_task_write_access(user, template_code, report_month)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    suffix = Path(file.filename).suffix
    content = await file.read(MAX_WORKBOOK_SIZE_BYTES + 1)
    if len(content) > MAX_WORKBOOK_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="上传文件不能超过 20MB")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(content)
        temp_path = Path(temp_file.name)
    try:
        return service.create_import(user, temp_path, file.filename, template_code, report_month=report_month)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)


@router.get("/api/imports")
def list_imports(report_month: Optional[str] = None, status: Optional[str] = None, user=Depends(active_user)):
    return service.list_imports(user, report_month=report_month, status=status)


@router.get("/api/imports/{batch_id}")
def get_import(batch_id: int, user=Depends(active_user)):
    try:
        return service.get_import(user, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/imports/{batch_id}/file")
def download_import_file(batch_id: int, user=Depends(active_user)):
    try:
        path, filename = service.get_import_file(user, batch_id)
        return FileResponse(path, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/imports/{batch_id}/preview")
def get_import_preview(batch_id: int, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), sheet_name: Optional[str] = Query(None), limit: Optional[int] = Query(None, ge=1, le=100), user=Depends(active_user)):
    try:
        return service.get_import_preview(user, batch_id, page=page, page_size=page_size, sheet_name=sheet_name, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/imports/{batch_id}/validation-report")
def get_validation_report(batch_id: int, user=Depends(active_user)):
    try:
        return service.get_validation_report(user, batch_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/imports/{batch_id}/commit")
def commit_import(batch_id: int, payload: CommitRequest, response: Response, user=Depends(active_user)):
    try:
        result = service.commit_import(user, batch_id, report_month=payload.report_month)
        if result["status"] == "recovery_required":
            response.status_code = 202
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/imports/{batch_id}/void")
def void_import(batch_id: int, payload: VoidRequest, response: Response, user=Depends(active_user)):
    try:
        result = service.void_import(user, batch_id, payload.reason, report_month=payload.report_month)
        if result["status"] == "recovery_required":
            response.status_code = 202
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/records")
def list_records(report_month: Optional[str] = None, user=Depends(active_user)):
    return database.list_records(user, report_month=report_month)


@router.get("/api/write-operations")
def list_write_operations(user=Depends(admin_user)):
    return database.list_write_operations()


@router.post("/api/write-operations/{operation_id}/retry")
def retry_write_operation(operation_id: int, response: Response, user=Depends(admin_user)):
    try:
        result = database.retry_write_operation(operation_id)
        if result["status"] == "recovery_required":
            response.status_code = 202
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/write-operations/{operation_id}/rebuild-empty-target")
def rebuild_empty_target_operation(operation_id: int, response: Response, user=Depends(admin_user)):
    try:
        result = database.rebuild_empty_target_operation(user, operation_id)
        if result["status"] == "recovery_required":
            response.status_code = 202
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
