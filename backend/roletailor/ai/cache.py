"""Exact-match response cache keyed by (model, prompt version hash, payload).

Identical requests (re-runs, retries after a downstream failure, the same JD across
users of a tenant) cost nothing. Redis in deployed environments, memory otherwise.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Protocol

log = logging.getLogger(__name__)


def cache_key(model: str, prompt_sha: str, user: str, schema: dict) -> str:
    h = hashlib.sha256()
    for part in (model, prompt_sha, user, json.dumps(schema, sort_keys=True)):
        h.update(part.encode())
        h.update(b"\x00")
    return "rt:llm:" + h.hexdigest()


class ResponseCache(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, ttl_s: int) -> None: ...


class MemoryCache:
    def __init__(self, max_items: int = 2048):
        self._data: dict[str, str] = {}
        self._max = max_items
        self._lock = threading.Lock()

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str, ttl_s: int) -> None:
        with self._lock:
            if len(self._data) >= self._max:
                self._data.pop(next(iter(self._data)))
            self._data[key] = value


class RedisCache:
    """Cache failures degrade to a miss; they never fail a generation."""

    def __init__(self, url: str):
        import redis

        self._r = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)

    def get(self, key: str) -> str | None:
        try:
            v = self._r.get(key)
        except Exception as e:  # noqa: BLE001
            log.warning("llm cache get failed: %s", e)
            return None
        return v.decode() if v else None

    def set(self, key: str, value: str, ttl_s: int) -> None:
        try:
            self._r.set(key, value, ex=ttl_s)
        except Exception as e:  # noqa: BLE001
            log.warning("llm cache set failed: %s", e)
