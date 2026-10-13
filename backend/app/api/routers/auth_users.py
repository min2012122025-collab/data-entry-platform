"""Authentication, current-account, and employee administration endpoints."""

from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response

from ...container import database
from ...core.config import settings
from ...core.login_throttle import login_throttle
from ..dependencies import admin_user, current_user
from ..schemas import LoginRequest, PasswordChangeRequest, PasswordResetRequest, UserCreateRequest, UserUpdateRequest


router = APIRouter(tags=["authentication and users"])


@router.post("/api/auth/login")
def login(payload: LoginRequest, response: Response, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    retry_after = login_throttle.retry_after(payload.username, client_ip)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="登录尝试过多，请稍后重试",
            headers={"Retry-After": str(retry_after)},
        )
    user = database.authenticate(payload.username, payload.password)
    if not user:
        retry_after = login_throttle.record_failure(payload.username, client_ip)
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="登录尝试过多，请稍后重试",
                headers={"Retry-After": str(retry_after)},
            )
        raise HTTPException(status_code=401, detail="账号或密码不正确")
    login_throttle.clear(payload.username, client_ip)
    token = database.create_session(user["id"])
    response.set_cookie(
        settings.session_cookie,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
        max_age=settings.session_hours * 3600,
    )
    return {"user": user}


@router.post("/api/auth/logout")
def logout(response: Response, entry_session: Optional[str] = Cookie(default=None)):
    database.revoke_session(entry_session)
    response.delete_cookie(
        settings.session_cookie,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@router.post("/api/auth/change-password")
def change_password(
    payload: PasswordChangeRequest,
    user=Depends(current_user),
    entry_session: Optional[str] = Cookie(default=None),
):
    try:
        database.change_password(
            user["id"], payload.current_password, payload.new_password, current_token=entry_session
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/api/me")
def me(user=Depends(current_user)):
    return {"user": user}


@router.get("/api/users")
def list_users(include_archived: bool = False, user=Depends(admin_user)):
    return database.list_users(include_archived=include_archived)


@router.get("/api/users/{user_id}/deletion-impact")
def user_deletion_impact(user_id: int, user=Depends(admin_user)):
    try:
        return database.user_deletion_impact(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/api/users/{user_id}")
def delete_user(user_id: int, user=Depends(admin_user)):
    try:
        return database.archive_user(user["id"], user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/users/{user_id}/restore")
def restore_user(user_id: int, user=Depends(admin_user)):
    try:
        return database.restore_user(user["id"], user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/users")
def create_user(payload: UserCreateRequest, user=Depends(admin_user)):
    try:
        return database.create_user(user["id"], payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/api/users/{user_id}")
def update_user(user_id: int, payload: UserUpdateRequest, user=Depends(admin_user)):
    try:
        return database.update_user(user["id"], user_id, payload.model_dump(exclude_unset=True))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/users/{user_id}/reset-password")
def reset_user_password(user_id: int, payload: PasswordResetRequest, user=Depends(admin_user)):
    try:
        return database.reset_user_password(user["id"], user_id, payload.new_password)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
