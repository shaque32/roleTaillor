"""Transactional email behind a small provider interface.

Services build an `EmailMessage` (see `templates`) and hand it to `get_provider().send`.
Which provider that is comes from RT_EMAIL_PROVIDER, so swapping Resend for another
service is one new class here and nothing else.
"""

from roletailor.mailer.provider import (
    ConsoleProvider,
    EmailMessage,
    EmailProvider,
    EmailSendError,
    MemoryProvider,
    ResendProvider,
    get_provider,
)

__all__ = [
    "ConsoleProvider", "EmailMessage", "EmailProvider", "EmailSendError", "MemoryProvider",
    "ResendProvider", "get_provider",
]
