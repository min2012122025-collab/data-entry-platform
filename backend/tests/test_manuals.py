import os
from pathlib import Path

from fastapi.testclient import TestClient


os.environ.setdefault("ENTRY_ENV", "test")
os.environ.setdefault("ENTRY_ALLOW_SQLITE", "1")
os.environ.setdefault("ENTRY_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ENTRY_SECRET_KEY", "test-secret-key-for-manuals")
os.environ.setdefault("ENTRY_COOKIE_SECURE", "0")

from app.core.config import settings  # noqa: E402
from app.api.dependencies import active_user, admin_user, current_user  # noqa: E402
from app.api.routers import manuals  # noqa: E402
from app.main import create_app  # noqa: E402


def client_with_data_dir(tmp_path, monkeypatch, role="submitter"):
    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(manuals, "BUNDLED_MANUAL_DIR", tmp_path / "bundled-manuals")
    user = {
        "id": 1 if role == "admin" else 2,
        "username": role,
        "display_name": "管理员" if role == "admin" else "填报人员",
        "role": role,
        "department": "业务部门",
        "must_change_password": False,
    }
    app = create_app()
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[active_user] = lambda: user
    if role == "admin":
        app.dependency_overrides[admin_user] = lambda: user
    return TestClient(app)


def test_manual_list_reports_available_initial_manuals(tmp_path, monkeypatch):
    client = client_with_data_dir(tmp_path, monkeypatch)
    manuals_dir = settings.data_dir / "manuals"
    manuals_dir.mkdir(parents=True)
    (manuals_dir / "submitter.html").write_text("<h1>填报人员手册</h1>", encoding="utf-8")

    response = client.get("/api/manuals")

    assert response.status_code == 200
    assert response.json()["manuals"] == [
        {
            "role": "submitter",
            "label": "填报人员手册",
            "available": True,
            "content_type": "text/html; charset=utf-8",
            "filename": "submitter.html",
            "url": "/api/manuals/submitter",
        },
        {
            "role": "admin",
            "label": "管理员手册",
            "available": False,
            "content_type": None,
            "filename": None,
            "url": None,
        },
    ]


def test_submitter_cannot_upload_manual(tmp_path, monkeypatch):
    client = client_with_data_dir(tmp_path, monkeypatch)

    response = client.post(
        "/api/manuals/submitter",
        files={"file": ("submitter.html", b"<h1>new</h1>", "text/html")},
    )

    assert response.status_code == 403


def test_admin_uploads_and_downloads_manual(tmp_path, monkeypatch):
    client = client_with_data_dir(tmp_path, monkeypatch, role="admin")

    upload = client.post(
        "/api/manuals/admin",
        files={"file": ("admin.pdf", b"%PDF-1.4\nmanual", "application/pdf")},
    )
    assert upload.status_code == 200
    assert upload.json()["manual"]["filename"] == "admin.pdf"

    download = client.get("/api/manuals/admin")

    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.content == b"%PDF-1.4\nmanual"
    assert Path(settings.data_dir / "manuals" / "admin.pdf").is_file()
