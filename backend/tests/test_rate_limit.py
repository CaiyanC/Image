import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.core.rate_limit import (
    enforce_rate_limit,
    get_request_identifier,
    reset_rate_limits,
    set_rate_limit_redis_client,
)
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

    def test_uses_bounded_local_fallback_when_redis_is_unavailable(self):
        set_rate_limit_redis_client(FailingRedis())

        with self.assertLogs("app.rate_limit", level="WARNING") as logs:
            enforce_rate_limit(user_id="user-1", scope="auth.login", limit=1, window_seconds=60)

        self.assertIn("using bounded in-process rate limit fallback", "\n".join(logs.output))
        with self.assertRaises(HTTPException) as caught:
            enforce_rate_limit(user_id="user-1", scope="auth.login", limit=1, window_seconds=60)
        self.assertEqual(caught.exception.status_code, 429)

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

    def test_untrusted_peer_cannot_override_identifier_with_forwarded_header(self):
        request = SimpleNamespace(
            headers={"x-forwarded-for": "198.51.100.77"},
            client=SimpleNamespace(host="203.0.113.10"),
        )

        with patch.dict("os.environ", {"TRUSTED_PROXY_CIDRS": "127.0.0.1/32"}):
            self.assertEqual(get_request_identifier(request), "203.0.113.10")

    def test_trusted_proxy_uses_rightmost_untrusted_forwarded_address(self):
        request = SimpleNamespace(
            headers={"x-forwarded-for": "198.51.100.77, 203.0.113.10"},
            client=SimpleNamespace(host="127.0.0.1"),
        )

        with patch.dict("os.environ", {"TRUSTED_PROXY_CIDRS": "127.0.0.1/32"}):
            self.assertEqual(get_request_identifier(request), "203.0.113.10")

    def test_trusted_multi_proxy_chain_skips_every_trusted_hop(self):
        request = SimpleNamespace(
            headers={"x-forwarded-for": "198.51.100.77, 10.0.0.8"},
            client=SimpleNamespace(host="127.0.0.1"),
        )

        with patch.dict(
            "os.environ",
            {"TRUSTED_PROXY_CIDRS": "127.0.0.1/32,10.0.0.0/24"},
        ):
            self.assertEqual(get_request_identifier(request), "198.51.100.77")


if __name__ == "__main__":
    unittest.main()
