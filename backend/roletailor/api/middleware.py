"""Correlation ids and request metrics (pure ASGI, so streaming responses are untouched)."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from roletailor.api.metrics import HTTP_LATENCY, HTTP_REQUESTS
from roletailor.logging_setup import correlation_id

log = logging.getLogger("roletailor.access")
HEADER = b"x-correlation-id"
_VALID_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _route_template(scope: Scope) -> str:
    """The matched path with parameter values put back as {names}, to keep label
    cardinality bounded (routes are nested, so the route object holds only a suffix)."""
    if scope.get("route") is None:
        return "unmatched"
    path = scope["path"]
    for name, value in (scope.get("path_params") or {}).items():
        path = path.replace(f"/{value}", f"/{{{name}}}", 1)
    return path


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(HEADER, b"").decode("latin-1")
        cid = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        token = correlation_id.set(cid)
        started = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"].append((HEADER, cid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            template = _route_template(scope)
            elapsed = time.perf_counter() - started
            HTTP_REQUESTS.labels(scope["method"], template, str(status)).inc()
            HTTP_LATENCY.labels(scope["method"], template).observe(elapsed)
            log.info("request", extra={"method": scope["method"], "route": template, "status": status,
                                       "duration_ms": round(elapsed * 1000, 1)})
            correlation_id.reset(token)
