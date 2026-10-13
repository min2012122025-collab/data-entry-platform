"""Public brand display and administrator-only persistent customization."""

import hashlib
import io
import json
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, field_validator

from ...core.config import settings
from ..dependencies import admin_user

router = APIRouter(tags=['branding'])
lock = RLock()
DEFAULT_NAME = '通用录入平台'
DEFAULT_LOGO = '/assets/default-brand.svg'
MAX_BYTES = 2 * 1024 * 1024


class BrandName(BaseModel):
    name: str

    @field_validator('name')
    @classmethod
    def validate_name(cls, value):
        value = value.strip()
        if not 1 <= len(value) <= 60 or any(c in '<>' or ord(c) < 32 for c in value):
            raise ValueError('平台名称须为 1–60 个字符，不能包含标签或控制字符')
        return value


def directory() -> Path:
    return settings.data_dir / 'branding'


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@router.get('/api/branding')
def get_branding():
    with lock:
        config = directory() / 'config.json'
        name = json.loads(config.read_text())['name'] if config.is_file() else DEFAULT_NAME
        logo = directory() / 'logo.png'
        logo_url = f'/api/branding/logo?v={hashlib.sha256(logo.read_bytes()).hexdigest()[:16]}' if logo.is_file() else DEFAULT_LOGO
        return {'name': name, 'logo_url': logo_url}


@router.put('/api/branding')
def update_branding(payload: BrandName, user=Depends(admin_user)):
    with lock:
        atomic_write(directory() / 'config.json', json.dumps({'name': payload.name}, ensure_ascii=False).encode())
        return get_branding()


@router.get('/api/branding/logo')
def get_logo():
    path = directory() / 'logo.png'
    if not path.is_file():
        raise HTTPException(status_code=404, detail='尚未上传品牌图片')
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/api/branding/logo')
async def upload_logo(file: UploadFile = File(...), user=Depends(admin_user)):
    content = await file.read(MAX_BYTES + 1)
    if not content or len(content) > MAX_BYTES:
        raise HTTPException(status_code=400, detail='品牌图片须为非空文件，且不能超过 2MB')
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or max(image.size) > 2048:
                raise ValueError('unsupported image')
            image.load()
            # Re-encode pixel data, discarding EXIF, comments, and embedded payloads.
            clean = Image.new('RGBA', image.size)
            clean.paste(image.convert('RGBA'))
            stream = io.BytesIO()
            clean.save(stream, format='PNG')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=400, detail='请选择有效的 PNG、JPEG 或 WebP 图片，尺寸不能超过 2048 × 2048') from exc
    with lock:
        atomic_write(directory() / 'logo.png', stream.getvalue())
        return get_branding()


@router.delete('/api/branding/logo')
def reset_logo(user=Depends(admin_user)):
    with lock:
        (directory() / 'logo.png').unlink(missing_ok=True)
        return get_branding()
