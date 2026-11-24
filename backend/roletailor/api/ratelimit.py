"""Fixed-window rate limiter on Redis, with an in-process fallback when Redis is down."""

from __future__ import annotations

import logging
import threading
import time

import redis

log = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, redis_url: str, prefix: str = "rl"):
        self._redis = redis.Redis.from_url(redis_url, socket_timeout=0.25, socket_connect_timeout=0.25)
        self._prefix = prefix
        self._local: dict[str, tuple[int, int]] = {}  # key -> (window, count)
        self._lock = threading.Lock()

    def hit(self, scope: str, identity: str, limit: int, window_s: int = 60) -> int | None:
        """Count one request. Returns seconds until the window resets when over the limit."""
        window = int(time.time()) // window_s
        key = f"{self._prefix}:{scope}:{identity}:{window}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_s + 1)
            count = int(pipe.execute()[0])
        except redis.RedisError:
            log.warning("rate limiter falling back to in-memory counters")
            count = self._local_hit(key, window)
        if count > limit:
            return window_s - int(time.time()) % window_s
        return None

    def _local_hit(self, key: str, window: int) -> int:
        with self._lock:
            if len(self._local) > 10_000:
                self._local = {k: v for k, v in self._local.items() if v[0] == window}
            _, count = self._local.get(key, (window, 0))
            self._local[key] = (window, count + 1)
            return count + 1
