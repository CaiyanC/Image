from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from app.core.business_scope import is_retired_api
from app.main import app
from app.services.upload_validation_service import validate_docx_content
from app.services.product_service import validate_product_payload
from fastapi import HTTPException


def docx_bytes(extra=None):
    stream = BytesIO()
    with ZipFile(stream, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', '<document/>')
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return stream.getvalue()


@pytest.mark.parametrize('path', ['/api/generation', '/api/generation/txt2img', '/api/history', '/api/loading-rates/calculate',
    '/api/tools/ecommerce-data-fill/drafts/a/files', '/api/tools/ecommerce-data-fill/runs/a/files/0', '/api/admin/tools'])
def test_retired_api_returns_gone_without_executing(path):
    client = TestClient(app)
    assert client.get(path).status_code == 410
    assert client.post(path, json={}).status_code == 410


@pytest.mark.parametrize('path', ['/api/customer-service', '/api/products', '/api/knowledge-base', '/api/tools',
    '/api/generation-other', '/api/files', '/api/admin/settings'])
def test_scope_does_not_capture_retained_or_similar_paths(path):
    assert not is_retired_api(path)


def test_word_bytes_pass_existing_archive_limits():
    validate_docx_content(docx_bytes())


@pytest.mark.parametrize('extra', [{'../escaped': 'x'}, {'word/vbaProject.bin': 'x'}, {'word/embeddings/object.bin': 'x'}, {'word/activeX/control.xml': 'x'}])
def test_word_active_content_and_unsafe_paths_rejected(extra):
    with pytest.raises(ValueError):
        validate_docx_content(docx_bytes(extra))


def test_fake_word_is_rejected():
    with pytest.raises(ValueError):
        validate_docx_content(b'not a word document')


def test_prelaunch_identity_can_leave_unknown_fields_empty():
    validate_product_payload({'sku': 'NEW-1', 'product_name_cn': '未上市产品', 'lifecycle_status': '未上市新品'})


@pytest.mark.parametrize('payload', [
    {'sku': 'NEW-1', 'lifecycle_status': '未上市新品'},
    {'product_name_cn': '未上市产品', 'lifecycle_status': '未上市新品'},
    {'sku': 'NEW-1', 'product_name_cn': '已上市产品', 'lifecycle_status': '常规品'},
])
def test_missing_identity_or_on_sale_fields_are_rejected(payload):
    with pytest.raises(HTTPException):
        validate_product_payload(payload)
