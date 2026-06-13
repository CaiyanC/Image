import asyncio
import base64
import contextlib
import io
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.database import Base
from app.core.config import settings
from app.api import auth as auth_api
from app.api import customer_service as customer_service_api
from app.api import generation as generation_api
from app.api import products as products_api
from app.api import users as users_api
from app.models.product import Product
from app.schemas.generation import ImagePayload
from app.schemas.user import UserCreate
from app.services import agent_trace_service, operation_log_service


class FakeUpload:
    def __init__(self, content: bytes, filename: str = "ref.png", content_type: str = "image/png"):
        self.content = content
        self.filename = filename
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self.content
        return self.content[:size]


class FakeProductUpload:
    def __init__(self, content: bytes, filename: str, content_type: str):
        self.filename = filename
        self.content_type = content_type
        self.file = io.BytesIO(content)


class ApiInputSafetyTest(unittest.TestCase):
    def test_public_registration_is_disabled_by_default(self):
        original = settings.ENABLE_PUBLIC_REGISTRATION
        settings.ENABLE_PUBLIC_REGISTRATION = False
        try:
            with self.assertRaises(HTTPException) as ctx:
                auth_api.register(
                    UserCreate(username="public-user", email=None, password="StrongPass123"),
                    db=None,
                )
            self.assertEqual(ctx.exception.status_code, 403)
        finally:
            settings.ENABLE_PUBLIC_REGISTRATION = original

    def test_new_user_password_requires_minimum_length(self):
        with self.assertRaises(ValidationError):
            UserCreate(username="weak-user", email=None, password="1234567")

    def test_trace_defaults_to_no_stdout_and_masks_sensitive_payload(self):
        original_stdout = agent_trace_service.TRACE_STDOUT
        original_full_payload = agent_trace_service.TRACE_FULL_PAYLOAD
        try:
            agent_trace_service.TRACE_STDOUT = False
            agent_trace_service.TRACE_FULL_PAYLOAD = True

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                line = agent_trace_service._format_trace_line(
                    "TOOL_CALL",
                    {"api_key": "sk-secret", "prompt": "x" * 500, "items": [{"token": "abc"}]},
                )
                agent_trace_service.trace("TOOL_CALL", {"api_key": "sk-secret"})

            self.assertEqual(buffer.getvalue(), "")
            self.assertIn('"api_key": "***"', line)
            self.assertIn('"token": "***"', line)
            self.assertNotIn("sk-secret", line)
            self.assertNotIn("abc", line)
        finally:
            agent_trace_service.TRACE_STDOUT = original_stdout
            agent_trace_service.TRACE_FULL_PAYLOAD = original_full_payload

    def test_operation_log_sanitizes_sensitive_key_variants(self):
        sanitized = operation_log_service._sanitize({
            "Password": "plain",
            "apiKey": "sk-secret",
            "access_token": "token",
            "Authorization": "Bearer token",
            "nested": [{"clientSecret": "secret"}, {"safe": "ok"}],
        })

        self.assertEqual(sanitized["Password"], "***")
        self.assertEqual(sanitized["apiKey"], "***")
        self.assertEqual(sanitized["access_token"], "***")
        self.assertEqual(sanitized["Authorization"], "***")
        self.assertEqual(sanitized["nested"][0]["clientSecret"], "***")
        self.assertEqual(sanitized["nested"][1]["safe"], "ok")

    def test_missing_user_response_is_404_not_500(self):
        with self.assertRaises(HTTPException) as ctx:
            users_api._enrich_user_response(None, None)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_customer_service_request_rejects_unbounded_question(self):
        with self.assertRaises(ValidationError):
            customer_service_api.CustomerServiceAskRequest(question="x" * 2001)

    def test_stream_error_message_does_not_expose_exception_text(self):
        message = customer_service_api._public_error_message()
        self.assertIn("智能客服", message)
        self.assertNotIn("Traceback", message)
        self.assertNotIn("Exception", message)

    def test_customer_service_pagination_has_server_side_bounds(self):
        routes = {route.path: route for route in customer_service_api.router.routes}
        conversation_params = {
            param.name: str(param.field_info.metadata)
            for param in routes["/api/customer-service/conversations"].dependant.query_params
        }
        review_params = {
            param.name: str(param.field_info.metadata)
            for param in routes["/api/customer-service/review-samples"].dependant.query_params
        }

        self.assertIn("Ge(ge=0)", conversation_params["skip"])
        self.assertIn("Ge(ge=1)", conversation_params["limit"])
        self.assertIn("Le(le=100)", conversation_params["limit"])
        self.assertIn("Ge(ge=1)", review_params["limit"])
        self.assertIn("Le(le=500)", review_params["limit"])

    def test_core_list_routes_have_server_side_pagination_bounds(self):
        def route_by_path_and_method(router, path: str, method: str):
            for route in router.routes:
                if route.path == path and method in route.methods:
                    return route
            raise AssertionError(f"route not found: {method} {path}")

        product_params = {
            param.name: str(param.field_info.metadata)
            for param in route_by_path_and_method(products_api.router, "/api/products", "GET").dependant.query_params
        }
        product_search_params = {
            param.name: str(param.field_info.metadata)
            for param in route_by_path_and_method(products_api.router, "/api/products/search", "GET").dependant.query_params
        }
        user_params = {
            param.name: str(param.field_info.metadata)
            for param in route_by_path_and_method(users_api.router, "/api/users", "GET").dependant.query_params
        }

        for params in (product_params, product_search_params, user_params):
            self.assertIn("Ge(ge=0)", params["skip"])
            self.assertIn("Ge(ge=1)", params["limit"])
        self.assertIn("Le(le=100)", product_params["limit"])
        self.assertIn("Le(le=100)", product_search_params["limit"])
        self.assertIn("Le(le=200)", user_params["limit"])

    def test_full_product_update_missing_product_is_404_before_payload_validation(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[Product.__table__])
        db = sessionmaker(bind=engine)()
        try:
            with self.assertRaises(HTTPException) as ctx:
                products_api.update_product_full(
                    "NO-SUCH-SKU",
                    {},
                    request=None,
                    current_user=None,
                    db=db,
                )
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            db.close()

    def test_reference_upload_rejects_unsupported_extension(self):
        upload = FakeUpload(b"hello", filename="ref.txt", content_type="text/plain")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(generation_api._read_reference_upload(upload))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_reference_upload_rejects_oversized_image(self):
        content = b"x" * (generation_api.MAX_REFERENCE_IMAGE_BYTES + 1)
        upload = FakeUpload(content, filename="ref.png", content_type="image/png")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(generation_api._read_reference_upload(upload))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_base64_reference_payload_validation(self):
        content, ext = generation_api._decode_reference_payload(
            ImagePayload(data=base64.b64encode(b"image").decode("ascii"), mimeType="image/webp")
        )
        self.assertEqual(content, b"image")
        self.assertEqual(ext, "webp")

        with self.assertRaises(HTTPException):
            generation_api._decode_reference_payload(ImagePayload(data="not-base64", mimeType="image/png"))

    def test_product_image_upload_rejects_type_and_size_abuse(self):
        bad_type = FakeProductUpload(b"hello", "shell.exe", "application/octet-stream")
        with self.assertRaises(HTTPException):
            products_api._validate_media_upload(
                bad_type,
                allowed_suffixes=products_api.ALLOWED_PRODUCT_IMAGE_SUFFIXES,
                allowed_mime_types=products_api.ALLOWED_PRODUCT_IMAGE_MIME_TYPES,
            )

        oversized = FakeProductUpload(b"x" * (products_api.MAX_PRODUCT_IMAGE_BYTES + 1), "ref.png", "image/png")
        with self.assertRaises(HTTPException) as ctx:
            products_api._read_limited_upload(oversized, products_api.MAX_PRODUCT_IMAGE_BYTES, "图片不能超过 10MB")
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
