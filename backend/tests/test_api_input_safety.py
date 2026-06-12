import asyncio
import base64
import contextlib
import io
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from app.api import customer_service as customer_service_api
from app.api import generation as generation_api
from app.schemas.generation import ImagePayload
from app.services import agent_trace_service


class FakeUpload:
    def __init__(self, content: bytes, filename: str = "ref.png", content_type: str = "image/png"):
        self.content = content
        self.filename = filename
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self.content
        return self.content[:size]


class ApiInputSafetyTest(unittest.TestCase):
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

    def test_customer_service_request_rejects_unbounded_question(self):
        with self.assertRaises(ValidationError):
            customer_service_api.CustomerServiceAskRequest(question="x" * 2001)

    def test_stream_error_message_does_not_expose_exception_text(self):
        message = customer_service_api._public_error_message()
        self.assertIn("智能客服", message)
        self.assertNotIn("Traceback", message)
        self.assertNotIn("Exception", message)

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


if __name__ == "__main__":
    unittest.main()
