import unittest

from fastapi import HTTPException

from app.core.rate_limit import enforce_rate_limit, reset_rate_limits, set_rate_limit_redis_client
from tests.rate_limit_fakes import FailingRedis, FakeRedis


class RateLimitTest(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        set_rate_limit_redis_client(self.redis)
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

    def test_first_request_sets_ttl_for_new_bucket(self):
        enforce_rate_limit(user_id="user-1", scope="auth.login", limit=8, window_seconds=60)

        self.assertEqual(self.redis.ttl("rate_limit:auth.login:user-1"), 60)
        self.assertEqual(self.redis.expire_calls, [("rate_limit:auth.login:user-1", 60)])

    def test_existing_bucket_with_positive_ttl_does_not_refresh_expiry(self):
        key = "rate_limit:auth.login:user-1"
        self.redis.values[key] = 1
        self.redis.expirations[key] = 17

        enforce_rate_limit(user_id="user-1", scope="auth.login", limit=8, window_seconds=60)

        self.assertEqual(self.redis.ttl(key), 17)
        self.assertEqual(self.redis.expire_calls, [])

    def test_existing_bucket_without_ttl_is_healed_without_resetting_count(self):
        key = "rate_limit:auth.login:user-1"
        self.redis.values[key] = 3

        enforce_rate_limit(user_id="user-1", scope="auth.login", limit=8, window_seconds=60)

        self.assertEqual(self.redis.values[key], 4)
        self.assertEqual(self.redis.ttl(key), 60)
        self.assertEqual(self.redis.expire_calls, [(key, 60)])

    def test_over_limit_bucket_without_ttl_still_blocks_but_gets_expiry(self):
        key = "rate_limit:auth.login:user-1"
        self.redis.values[key] = 8

        with self.assertRaises(HTTPException) as caught:
            enforce_rate_limit(user_id="user-1", scope="auth.login", limit=8, window_seconds=60)

        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(self.redis.values[key], 9)
        self.assertEqual(self.redis.ttl(key), 60)
        self.assertEqual(self.redis.expire_calls, [(key, 60)])


if __name__ == "__main__":
    unittest.main()
