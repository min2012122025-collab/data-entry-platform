"""Operation manual listing, download, and administrator uploads."""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ...core.config import BASE_DIR, settings
from ..dependencies import active_user, admin_user


router = APIRouter(tags=["operation manuals"])

MANUALS = {
    "submitter": "填报人员手册",
    "admin": "管理员手册",
}
ALLOWED_SUFFIXES = {
    ".html": "text/html; charset=utf-8",
    ".pdf": "application/pdf",
}
MAX_MANUAL_SIZE_BYTES = 20 * 1024 * 1024
BUNDLED_MANUAL_DIR = BASE_DIR / "frontend" / "dist" / "manuals"


def manual_dir() -> Path:
    return settings.data_dir / "manuals"


def manual_path(role: str) -> Path | None:
    if role not in MANUALS:
        raise HTTPException(status_code=404, detail="手册类型不存在")
    for directory in (manual_dir(), BUNDLED_MANUAL_DIR):
        for suffix in ALLOWED_SUFFIXES:
            path = directory / f"{role}{suffix}"
            if path.is_file():
                return path
    return None


def describe_manual(role: str) -> dict:
    path = manual_path(role)
    suffix = path.suffix.lower() if path else None
    return {
        "role": role,
        "label": MANUALS[role],
        "available": path is not None,
        "content_type": ALLOWED_SUFFIXES.get(suffix) if suffix else None,
        "filename": path.name if path else None,
        "url": f"/api/manuals/{role}" if path else None,
    }


@router.get("/api/manuals")
def list_manuals(user=Depends(active_user)):
    return {"manuals": [describe_manual(role) for role in ("submitter", "admin")]}


@router.get("/api/manuals/{role}")
def download_manual(role: str, user=Depends(active_user)):
    path = manual_path(role)
    if not path:
        raise HTTPException(status_code=404, detail="手册尚未上传")
    return FileResponse(path, media_type=ALLOWED_SUFFIXES[path.suffix.lower()])


@router.post("/api/manuals/{role}")
async def upload_manual(role: str, file: UploadFile = File(...), user=Depends(admin_user)):
    if role not in MANUALS:
        raise HTTPException(status_code=404, detail="手册类型不存在")
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择手册文件")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="操作手册仅支持 .html 或 .pdf")
    content = await file.read(MAX_MANUAL_SIZE_BYTES + 1)
    if len(content) > MAX_MANUAL_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="操作手册不能超过 20MB")

    directory = manual_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{role}{suffix}"
    temp_target = directory / f".{role}{suffix}.tmp"
    temp_target.write_bytes(content)
    for old_suffix in ALLOWED_SUFFIXES:
        old_path = directory / f"{role}{old_suffix}"
        if old_path != target:
            old_path.unlink(missing_ok=True)
    temp_target.replace(target)
    return {"manual": describe_manual(role)}
