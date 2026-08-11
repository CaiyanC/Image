from app.services.customer_cache_service import SharedJsonTTLCache


class _SharedFakeRedis:
    def __init__(self, store):
        self.store = store

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, _ttl, value):
        self.store[key] = value

    def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    def scan_iter(self, pattern):
        prefix = pattern.removesuffix("*")
        return [key for key in self.store if key.startswith(prefix)]


def test_shared_json_cache_is_visible_across_worker_instances(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    store = {}
    first = SharedJsonTTLCache(ttl_seconds=300, namespace="parity")
    second = SharedJsonTTLCache(ttl_seconds=300, namespace="parity")
    first.set_redis_client(_SharedFakeRedis(store))
    second.set_redis_client(_SharedFakeRedis(store))

    first.set("turn", {"answer": "同一份回答", "result_skus": ["SKU-1"]})

    assert second.get("turn") == {"answer": "同一份回答", "result_skus": ["SKU-1"]}


def test_shared_json_cache_namespaces_environment(monkeypatch):
    store = {}
    cache = SharedJsonTTLCache(ttl_seconds=300, namespace="parity")
    cache.set_redis_client(_SharedFakeRedis(store))
    monkeypatch.setenv("APP_ENV", "dev")
    cache.set("turn", {"answer": "开发"})
    monkeypatch.setenv("APP_ENV", "prod")

    assert cache.get("turn") is None
