import unittest

from fastapi import HTTPException

from app.core.rate_limit import enforce_rate_limit, reset_rate_limits


class RateLimitTest(unittest.TestCase):
    def setUp(self):
        reset_rate_limits()

    def tearDown(self):
        reset_rate_limits()

    def test_allows_requests_within_limit(self):
        enforce_rate_limit(user_id="user-1", scope="customer_service.ask", limit=2, window_seconds=60)
        enforce_rate_limit(user_id="user-1", scope="customer_service.ask", limit=2, window_seconds=60)

    def test_blocks_requests_over_limit_per_scope_and_user(self):
        enforce_rate_limit(user_id="user-1", scope="knowledge.reindex", limit=1, window_seconds=60)

        with self.assertRaises(HTTPException) as caught:
            enforce_rate_limit(user_id="user-1", scope="knowledge.reindex", limit=1, window_seconds=60)

        self.assertEqual(caught.exception.status_code, 429)

        enforce_rate_limit(user_id="user-2", scope="knowledge.reindex", limit=1, window_seconds=60)
        enforce_rate_limit(user_id="user-1", scope="other.scope", limit=1, window_seconds=60)

    def test_reset_clears_buckets(self):
        enforce_rate_limit(user_id="user-1", scope="knowledge.retry", limit=1, window_seconds=60)
        reset_rate_limits()

        enforce_rate_limit(user_id="user-1", scope="knowledge.retry", limit=1, window_seconds=60)


if __name__ == "__main__":
    unittest.main()
