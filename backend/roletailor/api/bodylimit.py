"""Request body size limits (pure ASGI).

Nothing downstream reads a body without a bound: FastAPI parses JSON bodies whole and
Starlette spools multipart uploads to disk before the route runs, so an unbounded body is
a memory and disk exhaustion vector. Declared sizes are rejected up front; chunked or
mis-declared bodies are cut off while streaming.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from roletailor.api.errors import error_response
from roletailor.config import get_settings
from roletailor.services.errors import AppError

MULTIPART_OVERHEAD_BYTES = 64 * 1024
WEBHOOK_BYTES = 1_000_000


def _too_large(limit: int) -> AppError:
    return AppError(413, "payload_too_large", f"The request body must be at most {limit} bytes.")


def limit_for(method: str, path: str) -> int:
    settings = get_settings()
    path = path.rstrip("/")
    if method == "POST" and path == "/v1/resumes":
        return settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
    if path == "/v1/billing/webhook":
        return WEBHOOK_BYTES
    return settings.max_json_body_bytes


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = limit_for(scope["method"], scope["path"])
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            error = _too_large(limit)
            await error_response(413, error.code, error.message, headers={"Connection": "close"})(
                scope, receive, send)
            return
        received = 0
        started = rejected = False

        async def limited_receive() -> Message:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request" and not rejected:
                received += len(message.get("body", b""))
                if received > limit:
                    # Answer 413 ourselves and tell the app the client went away, so it
                    # stops reading. FastAPI would turn an exception raised here into a 400.
                    rejected = True
                    if not started:
                        error = _too_large(limit)
                        await error_response(413, error.code, error.message, headers={"Connection": "close"})(
                            scope, receive, send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return  # the 413 is already on the wire
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, limited_receive, guarded_send)
