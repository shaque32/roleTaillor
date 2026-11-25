"""Email providers: Resend for deployed environments, console for dev, memory for tests."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol
from uuid import uuid4

import httpx

from roletailor.config import get_settings

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str
    kind: str  # short label for logs and provider tags, e.g. "verify_email"
    # Lets the provider drop a repeat of the same send (our own retries).
    idempotency_key: str = field(default_factory=lambda: uuid4().hex)


class EmailSendError(Exception):
    """The provider did not accept the message."""


class EmailProvider(Protocol):
    def send(self, message: EmailMessage) -> None:
        """Deliver one message or raise EmailSendError."""


class ConsoleProvider:
    """Writes the message to the log instead of sending it. The body holds the one-time
    link, so this is how a developer follows a verification or reset link locally. The
    config guard allows this provider in dev and test only, so a link never reaches a
    shared log."""

    def send(self, message: EmailMessage) -> None:
        log.info("email (console provider, not sent)\nTo: %s\nSubject: %s\n\n%s",
                 message.to, message.subject, message.text)


class MemoryProvider:
    """Keeps messages in a list for tests to inspect."""

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.outbox.append(message)


class ResendProvider:
    def __init__(self, api_key: str, sender: str, reply_to: str = "", *, timeout: float = 10.0,
                 attempts: int = 3, client: httpx.Client | None = None, backoff_seconds: float = 0.5):
        self._api_key = api_key
        self._sender = sender
        self._reply_to = reply_to
        self._attempts = max(1, attempts)
        self._backoff = backoff_seconds
        self._client = client or httpx.Client(timeout=timeout)

    def send(self, message: EmailMessage) -> None:
        payload: dict[str, object] = {
            "from": self._sender,
            "to": [message.to],
            "subject": message.subject,
            "text": message.text,
            "html": message.html,
            "tags": [{"name": "kind", "value": message.kind}],
        }
        if self._reply_to:
            payload["reply_to"] = self._reply_to
        headers = {"Authorization": f"Bearer {self._api_key}", "Idempotency-Key": message.idempotency_key}
        problem = "no attempt made"
        for attempt in range(self._attempts):
            if attempt:
                time.sleep(self._backoff * 2 ** (attempt - 1))
            try:
                response = self._client.post(RESEND_URL, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                problem = type(exc).__name__
                continue
            if response.is_success:
                return
            # The response body can echo the recipient; keep only the status and error name.
            problem = f"HTTP {response.status_code} {_error_name(response)}".strip()
            if response.status_code not in _RETRY_STATUSES:
                break
        raise EmailSendError(f"Resend did not accept the {message.kind} email: {problem}")


def _error_name(response: httpx.Response) -> str:
    try:
        name = response.json().get("name", "")
    except (ValueError, AttributeError):
        return ""
    return name if isinstance(name, str) else ""


@lru_cache
def get_provider() -> EmailProvider:
    settings = get_settings()
    if settings.email_provider == "resend":
        return ResendProvider(settings.resend_api_key, settings.email_from, settings.email_reply_to,
                              timeout=settings.email_send_timeout_seconds)
    if settings.email_provider == "memory":
        return MemoryProvider()
    return ConsoleProvider()
