"""FastAPI application assembly and production SPA hosting."""

import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routers import auth_users, catalog, imports, manuals, reporting, branding, settings as settings_router
from .container import database
from .core.config import BASE_DIR, settings


FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


def create_app() -> FastAPI:
    docs_enabled = not settings.is_production
    application = FastAPI(
        title="通用录入平台",
        version="1.0.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    @application.middleware("http")
    async def cache_policy(request, call_next):
        response = await call_next(request)
        if (
            request.url.path.startswith("/assets/")
            and re.search(r"-[A-Za-z0-9_-]{4,}\.[^./]+$", request.url.path)
            and response.status_code == 200
        ):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    if (FRONTEND_DIST / "assets").is_dir():
        application.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    application.include_router(branding.router)
    application.include_router(auth_users.router)
    application.include_router(catalog.router)
    application.include_router(reporting.router)
    application.include_router(imports.router)
    application.include_router(manuals.router)
    application.include_router(settings_router.router)

    @application.on_event("startup")
    def startup() -> None:
        database.verify_schema()
        if settings.is_production and settings.external_writes_enabled:
            database.reconcile_pending_operations()

    @application.get("/")
    def index():
        index_file = FRONTEND_DIST / "index.html"
        if not index_file.is_file():
            raise HTTPException(status_code=503, detail="前端尚未构建")
        return FileResponse(index_file, headers={"Cache-Control": "no-store"})

    @application.get("/manual-widget.js")
    def manual_widget_script():
        script_file = FRONTEND_DIST / "manual-widget.js"
        if not script_file.is_file():
            raise HTTPException(status_code=404, detail="手册入口脚本不存在")
        return FileResponse(script_file, media_type="text/javascript; charset=utf-8")

    @application.get("/manual-widget.css")
    def manual_widget_style():
        style_file = FRONTEND_DIST / "manual-widget.css"
        if not style_file.is_file():
            raise HTTPException(status_code=404, detail="手册入口样式不存在")
        return FileResponse(style_file, media_type="text/css; charset=utf-8")

    @application.get("/month-scope.js")
    def month_scope_script():
        script_file = FRONTEND_DIST / "month-scope.js"
        if not script_file.is_file():
            raise HTTPException(status_code=404, detail="月份口径脚本不存在")
        return FileResponse(script_file, media_type="text/javascript; charset=utf-8", headers={"Cache-Control": "no-store"})

    @application.get("/api/health")
    def health():
        database_status = database.health()
        return {
            "app": settings.app_name,
            "environment": settings.environment,
            "application_database_dialect": database_status["dialect"],
            "external_writes_enabled": settings.external_writes_enabled,
        }

    @application.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="接口不存在")
        if settings.is_production and (
            path == "openapi.json" or path == "docs" or path.startswith("docs/") or path == "redoc" or path.startswith("redoc/")
        ):
            raise HTTPException(status_code=404, detail="页面不存在")
        index_file = FRONTEND_DIST / "index.html"
        if not index_file.is_file():
            raise HTTPException(status_code=503, detail="前端尚未构建")
        return FileResponse(index_file, headers={"Cache-Control": "no-store"})

    return application


app = create_app()
