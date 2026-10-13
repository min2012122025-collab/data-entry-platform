"""Template catalog, version files, previews, and responsibility endpoints."""

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ...container import database, service
from ..dependencies import active_user, admin_user
from ..schemas import ResponsibilityRequest, TemplateHeaderRequest, TemplateVersionRequest, TemplateWriteRequest


router = APIRouter(tags=["templates and responsibilities"])


def require_template_version_file_access(user, template_code, version):
    if not database.can_access_template_version_file(user, template_code, version):
        raise HTTPException(status_code=403, detail="无权下载该模板版本")


@router.get("/api/templates")
def list_templates(include_archived: bool = False, report_month: Optional[str] = None, user=Depends(active_user)):
    templates = service.list_templates(include_archived=include_archived and user["role"] == "admin", report_month=report_month)
    if user["role"] == "admin":
        return templates
    owned_codes = {task["template"]["code"] for task in database.list_tasks(user)}
    return [template for template in templates if template["code"] in owned_codes]


@router.get("/api/templates/{template_code}")
def get_template(template_code: str, version: Optional[str] = None, report_month: Optional[str] = None, user=Depends(active_user)):
    try:
        template = service.get_template(template_code, version=version, report_month=report_month)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if user["role"] != "admin":
        owned_codes = {task["template"]["code"] for task in database.list_tasks(user)}
        if template_code not in owned_codes:
            raise HTTPException(status_code=403, detail="无权查看该模板")
    return template


@router.post("/api/templates")
def create_template(payload: TemplateWriteRequest, user=Depends(admin_user)):
    if not payload.code:
        raise HTTPException(status_code=400, detail="模板编码不能为空")
    try:
        return database.create_template(user["id"], payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/templates/{template_code}")
def update_template(template_code: str, payload: TemplateWriteRequest, user=Depends(admin_user)):
    try:
        return database.update_template(user["id"], template_code, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/templates/{template_code}/deletion-impact")
def template_deletion_impact(template_code: str, user=Depends(admin_user)):
    try:
        return database.template_deletion_impact(template_code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/templates/{template_code}")
def delete_template(template_code: str, user=Depends(admin_user)):
    try:
        return database.delete_template(user["id"], template_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/templates/{template_code}/restore")
def restore_template(template_code: str, user=Depends(admin_user)):
    try:
        return database.restore_template(user["id"], template_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/templates/{template_code}/versions")
def create_template_version(template_code: str, payload: TemplateVersionRequest, user=Depends(admin_user)):
    try:
        return database.create_template_version(user["id"], template_code, payload.version, payload.effective_month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/templates/{template_code}/versions/{version}/file")
async def upload_template_file(template_code: str, version: str, file: UploadFile = File(...), user=Depends(admin_user)):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(status_code=400, detail="模板文件仅支持 .xlsx 或 .xlsm")
    suffix = Path(file.filename).suffix.lower()
    content = await file.read(20 * 1024 * 1024 + 1)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(content)
        temp_path = Path(temp_file.name)
    if len(content) > 20 * 1024 * 1024:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="模板文件不能超过 20MB")
    try:
        return service.upload_template_file(user, template_code, version, temp_path, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)


@router.get("/api/templates/{template_code}/versions/{version}/file")
def download_version_template_file(template_code: str, version: str, mode: str = "blank", user=Depends(active_user)):
    if mode not in {"blank", "original"}:
        raise HTTPException(status_code=400, detail="不支持的下载模式")
    if mode == "original" and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可以下载原始模板文件")
    if mode == "blank":
        require_template_version_file_access(user, template_code, version)
    try:
        path, filename = service.get_template_file(template_code, version, blank=mode == "blank")
        return FileResponse(path, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/templates/{template_code}/versions/{version}/file-preview")
def preview_version_template_file(template_code: str, version: str, user=Depends(admin_user)):
    try:
        return service.get_template_file_preview(template_code, version)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/api/templates/{template_code}/versions/{version}/file-preview")
def confirm_version_template_headers(template_code: str, version: str, payload: TemplateHeaderRequest, user=Depends(admin_user)):
    try:
        return service.confirm_template_file_headers(user, template_code, version, payload.sheets)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/templates/{template_code}/sample")
def download_template_sample(template_code: str, user=Depends(active_user)):
    try:
        record = database.get_template_file_record(template_code)
        if not record:
            raise ValueError("模板文件未上传")
        require_template_version_file_access(user, template_code, record["version"])
        path, filename = service.get_template_file(template_code, blank=True)
        return FileResponse(path, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/templates/{template_code}/sample-preview")
def preview_template_sample(template_code: str, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user=Depends(admin_user)):
    try:
        preview = service.get_template_file_preview(template_code)
        sheets = preview["analysis"].get("sheets", [])
        rows = [
            {"row_number": row["row_number"], "sheet_name": sheet["name"], "payload": row["payload"]}
            for sheet in sheets for row in sheet.get("preview_rows", [])
        ]
        total_rows = len(rows)
        offset = (page - 1) * page_size
        return {
            "report_month": None,
            "summary": {"total_rows": total_rows, "valid_rows": total_rows, "blocking_errors": 0, "warning_errors": 0},
            "fields": preview["analysis"].get("fields", []),
            "sheet_names": [sheet["name"] for sheet in sheets],
            "rows": rows[offset : offset + page_size],
            "pagination": {"page": page, "page_size": page_size, "total_rows": total_rows, "total_pages": (total_rows + page_size - 1) // page_size if total_rows else 0},
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/responsibilities")
def list_responsibilities(report_month: Optional[str] = None, user=Depends(admin_user)):
    return database.list_responsibilities(report_month=report_month)


@router.post("/api/responsibilities")
def set_responsibility(payload: ResponsibilityRequest, user=Depends(admin_user)):
    try:
        return database.set_responsibility(user["id"], payload.template_code, payload.owner_user_id, payload.effective_month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/responsibilities/{responsibility_id}/deletion-impact")
def responsibility_deletion_impact(responsibility_id: int, user=Depends(admin_user)):
    try:
        return database.responsibility_deletion_impact(responsibility_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/responsibilities/{responsibility_id}")
def delete_responsibility(responsibility_id: int, user=Depends(admin_user)):
    try:
        return database.delete_responsibility(user["id"], responsibility_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
