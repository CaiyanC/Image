import unittest

from fastapi import HTTPException

from app.core.rate_limit import enforce_rate_limit, reset_rate_limits, set_rate_limit_redis_client
from tests.rate_limit_fakes import FailingRedis, FakeRedis


class RateLimitTest(unittest.TestCase):
    def setUp(self):
        set_rate_limit_redis_client(FakeRedis())
        reset_rate_limits()

    def tearDown(self):
        reset_rate_limits()
        set_rate_limit_redis_client(None)

    def test_allows_requests_within_limit(self):
        enforce_rate_limit(user_id="user-1", scope="customer_service.ask", limit=2, window_seconds=60)
        enforce_rate_limit(user_id="user-1", scope="customer_service.ask", limit=2, window_seconds=60)

    def test_blocks_requests_over_limit_per_scope_and_user(self):
        enforce_rate_limit(user_id="user-1", scope="knowledge.reindex", limit=1, window_seconds=60)

        with self.assertRaises(HTTPException) as caught:
            enforce_rate_limit(user_id="user-1", scope="knowledge.reindex", limit=1, window_seconds=60)

        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.detail, "请求过于频繁，请稍后再试")

        enforce_rate_limit(user_id="user-2", scope="knowledge.reindex", limit=1, window_seconds=60)
        enforce_rate_limit(user_id="user-1", scope="other.scope", limit=1, window_seconds=60)

    def test_reset_clears_buckets(self):
        enforce_rate_limit(user_id="user-1", scope="knowledge.retry", limit=1, window_seconds=60)
        reset_rate_limits()

        enforce_rate_limit(user_id="user-1", scope="knowledge.retry", limit=1, window_seconds=60)

    def test_fail_open_when_redis_is_unavailable(self):
        set_rate_limit_redis_client(FailingRedis())

        with self.assertLogs("app.rate_limit", level="WARNING") as logs:
            enforce_rate_limit(user_id="user-1", scope="auth.login", limit=1, window_seconds=60)

        self.assertIn("fail open and allow request", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
