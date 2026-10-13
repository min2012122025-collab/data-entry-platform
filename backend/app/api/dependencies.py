"""Authentication and authorization dependencies shared by routers."""

from typing import Optional

from fastapi import Cookie, Depends, HTTPException

from ..container import database
from ..core.config import settings


def current_user(entry_session: Optional[str] = Cookie(default=None)):
    user = database.get_user_by_session(entry_session)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return user


def active_user(user=Depends(current_user)):
    if user.get("must_change_password"):
        raise HTTPException(status_code=403, detail="首次登录或密码重置后必须先修改密码")
    return user


def admin_user(user=Depends(active_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


__all__ = ["active_user", "admin_user", "current_user", "settings"]
