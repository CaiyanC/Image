import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.api import auth as auth_api
from app.api import generation as generation_api
from app.core.rate_limit import reset_rate_limits, set_rate_limit_redis_client
from app.schemas.generation import Txt2ImgRequest
from app.schemas.user import LoginRequest, UserCreate
from tests.rate_limit_fakes import FakeRedis


class ApiRateLimitTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_rate_limit_redis_client(FakeRedis())
        reset_rate_limits()
        self.request = SimpleNamespace(headers={}, client=SimpleNamespace(host="203.0.113.10"))
        self.user = SimpleNamespace(id="rate-user")

    def tearDown(self):
        reset_rate_limits()
        set_rate_limit_redis_client(None)

    def test_login_rate_limit_uses_ip_and_username(self):
        with patch.object(auth_api.user_service, "get_user_by_username", return_value=None):
            for _ in range(8):
                with self.assertRaises(HTTPException) as ctx:
                    auth_api.login(LoginRequest(username="Alice", password="bad"), request=self.request, db=object())
                self.assertEqual(ctx.exception.status_code, 401)

            with self.assertRaises(HTTPException) as ctx:
                auth_api.login(LoginRequest(username="Alice", password="bad"), request=self.request, db=object())

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail, "请求过于频繁，请稍后再试")

    def test_register_rate_limit_uses_ip_and_username(self):
        original_public_registration = auth_api.settings.ENABLE_PUBLIC_REGISTRATION
        auth_api.settings.ENABLE_PUBLIC_REGISTRATION = False
        try:
            for _ in range(8):
                with self.assertRaises(HTTPException) as ctx:
                    auth_api.register(
                        UserCreate(username="NewUser", password="password123"),
                        request=self.request,
                        db=object(),
                    )
                self.assertEqual(ctx.exception.status_code, 403)

            with self.assertRaises(HTTPException) as ctx:
                auth_api.register(
                    UserCreate(username="NewUser", password="password123"),
                    request=self.request,
                    db=object(),
                )
        finally:
            auth_api.settings.ENABLE_PUBLIC_REGISTRATION = original_public_registration

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail, "请求过于频繁，请稍后再试")

    async def test_ai_generation_rate_limit_returns_429(self):
        service_mock = AsyncMock(return_value={"ok": True})
        with patch.object(generation_api.generation_service, "create_txt2img", service_mock):
            for _ in range(generation_api.AI_GENERATION_LIMIT_PER_MINUTE):
                await generation_api.txt2img(
                    Txt2ImgRequest(prompt="test"),
                    current_user=self.user,
                    db=object(),
                )

            with self.assertRaises(HTTPException) as ctx:
                await generation_api.txt2img(
                    Txt2ImgRequest(prompt="test"),
                    current_user=self.user,
                    db=object(),
                )

        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.detail, "请求过于频繁，请稍后再试")
        self.assertEqual(service_mock.await_count, generation_api.AI_GENERATION_LIMIT_PER_MINUTE)


if __name__ == "__main__":
    unittest.main()
