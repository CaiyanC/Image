from fnmatch import fnmatch

from redis import RedisError


class FakeRedis:
    def __init__(self):
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    def incr(self, key: str):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int):
        self.expirations[key] = seconds
        return True

    def scan_iter(self, pattern: str):
        for key in list(self.values):
            if fnmatch(key, pattern):
                yield key

    def delete(self, *keys: str):
        for key in keys:
            self.values.pop(key, None)
            self.expirations.pop(key, None)
        return len(keys)


class FailingRedis:
    def incr(self, key: str):
        raise RedisError("redis unavailable")

    def expire(self, key: str, seconds: int):
        raise RedisError("redis unavailable")

    def scan_iter(self, pattern: str):
        raise RedisError("redis unavailable")
