import io
import os

os.environ.setdefault('ENTRY_ENV', 'test')
os.environ.setdefault('ENTRY_ALLOW_SQLITE', '1')
os.environ.setdefault('ENTRY_DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('ENTRY_SECRET_KEY', 'test-branding-secret')

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.core.config import settings
from app.api.dependencies import current_user
from app.main import create_app


def client(tmp_path, monkeypatch, role='admin'):
    monkeypatch.setattr(settings, 'data_dir', tmp_path)
    app = create_app()
    app.dependency_overrides[current_user] = lambda: {
        'id': 1, 'role': role, 'disabled': False, 'must_change_password': False,
    }
    return TestClient(app)


def image_bytes():
    stream = io.BytesIO()
    Image.new('RGB', (24, 16), 'blue').save(stream, format='PNG')
    return stream.getvalue()


def test_brand_changes_survive_application_restart(tmp_path, monkeypatch):
    api = client(tmp_path, monkeypatch)
    assert api.get('/api/branding').json()['name'] == '通用录入平台'
    response = api.put('/api/branding', json={'name': '  示例平台  '})
    assert response.status_code == 200
    uploaded = api.post('/api/branding/logo', files={'file': ('logo.png', image_bytes(), 'image/png')})
    assert uploaded.status_code == 200
    restarted = client(tmp_path, monkeypatch)
    saved = restarted.get('/api/branding').json()
    assert saved['name'] == '示例平台'
    logo = restarted.get(saved['logo_url'])
    assert logo.status_code == 200
    assert Image.open(io.BytesIO(logo.content)).size == (24, 16)
    assert restarted.delete('/api/branding/logo').status_code == 200
    assert restarted.get('/api/branding').json()['logo_url'] == '/assets/default-brand.svg'
    assert restarted.get('/api/branding').json()['name'] == '示例平台'


@pytest.mark.parametrize('role', ['submitter', None])
def test_non_admin_cannot_change_brand(tmp_path, monkeypatch, role):
    api = client(tmp_path, monkeypatch, role)
    if role is None:
        def unauthenticated():
            from fastapi import HTTPException
            raise HTTPException(status_code=401)
        api.app.dependency_overrides[current_user] = unauthenticated
    for response in [
        api.put('/api/branding', json={'name': 'changed'}),
        api.post('/api/branding/logo', files={'file': ('logo.png', image_bytes(), 'image/png')}),
        api.delete('/api/branding/logo'),
    ]:
        assert response.status_code in (401, 403)
    assert api.get('/api/branding').json()['name'] == '通用录入平台'


@pytest.mark.parametrize('content', [b'not an image', b'<svg onload="alert(1)"/>', b'x' * (2 * 1024 * 1024 + 1)], ids=['invalid', 'svg', 'oversized'])
def test_bad_upload_preserves_previous_logo(tmp_path, monkeypatch, content):
    api = client(tmp_path, monkeypatch)
    assert api.post('/api/branding/logo', files={'file': ('good.png', image_bytes(), 'image/png')}).status_code == 200
    url = api.get('/api/branding').json()['logo_url']
    before = api.get(url).content
    invalid = api.post('/api/branding/logo', files={'file': ('bad.png', content, 'image/png')})
    assert invalid.status_code == 400
    assert api.get(url).content == before


@pytest.mark.parametrize('name', ['', '   ', 'x' * 61, '<script>bad</script>'])
def test_invalid_name_is_rejected(tmp_path, monkeypatch, name):
    api = client(tmp_path, monkeypatch)
    assert api.put('/api/branding', json={'name': name}).status_code == 422
    assert api.get('/api/branding').json()['name'] == '通用录入平台'
