"""Email verification and password reset.

Both flows hand the user a one-time link. The token in it is random (256 bits), carries an
HMAC so junk is rejected before any database work, is stored only as a SHA-256 hash,
expires, and is spent by a single atomic UPDATE, so two requests with the same link cannot
both succeed. A token also remembers the address it was mailed to and stops counting if
the account's address changes.

`request_password_reset` and `send_verification_email` run after the response has been
sent (FastAPI background tasks). The forgot-password endpoint therefore answers the same
way, in the same time, whether or not the address has an account.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Connection, text

from roletailor import db, mailer
from roletailor.config import get_settings
from roletailor.mailer import templates
from roletailor.services import audit
from roletailor.services.auth import (
    check_password_policy,
    hash_password,
    hash_token,
    memberships,
    normalize_email,
)
from roletailor.services.errors import AppError
from roletailor.services.sql import fetch_one

log = logging.getLogger(__name__)

VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"
_SIGNATURE_BYTES = 16


def _invalid_token() -> AppError:
    return AppError(400, "invalid_token", "This link is invalid or has expired. Request a new one.")


def _signature(purpose: str, secret: str) -> str:
    key = get_settings().secret_key.encode()
    digest = hmac.new(key, f"rt-email-token:{purpose}:{secret}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:_SIGNATURE_BYTES]).rstrip(b"=").decode()


def _well_signed(token: str, purpose: str) -> bool:
    secret, _, signature = token.partition(".")
    if not secret or not signature:
        return False
    return hmac.compare_digest(signature.encode(), _signature(purpose, secret).encode())


def issue_token(conn: Connection, user_id: UUID | str, purpose: str, email: str, ttl: timedelta) -> str:
    """Create a token for the user and retire any earlier unused one of the same purpose,
    so only the newest link works."""
    # Two issuances for one user and purpose must not overlap, or each would retire the
    # other's predecessors and both new links would stay live. An advisory lock (held to
    # the end of the transaction) serializes issuers without touching the users row,
    # which the consume paths lock after a token row.
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                 {"k": f"rt-user-token:{user_id}:{purpose}"})
    conn.execute(
        text("UPDATE user_tokens SET used_at = now()"
             " WHERE user_id = :uid AND purpose = :p AND used_at IS NULL"),
        {"uid": user_id, "p": purpose},
    )
    secret = secrets.token_urlsafe(32)
    token = f"{secret}.{_signature(purpose, secret)}"
    now = datetime.now(UTC)
    conn.execute(
        text("INSERT INTO user_tokens (user_id, purpose, token_hash, email, created_at, expires_at)"
             " VALUES (:uid, :p, :h, :e, :now, :exp)"),
        {"uid": user_id, "p": purpose, "h": hash_token(token), "e": email, "now": now, "exp": now + ttl},
    )
    return token


def consume_token(conn: Connection, token: str, purpose: str) -> dict | None:
    """Spend a token. Returns its user id and address, or None when it is malformed,
    unknown, expired, already used or meant for another purpose."""
    if len(token) > 200 or not _well_signed(token, purpose):
        return None
    return fetch_one(
        conn,
        "UPDATE user_tokens SET used_at = now()"
        " WHERE token_hash = :h AND purpose = :p AND used_at IS NULL AND expires_at > now()"
        " RETURNING user_id, email",
        {"h": hash_token(token), "p": purpose},
    )


def _link(page: str, token: str) -> str:
    # The token rides in the fragment, which browsers never send to a server, so it stays
    # out of access logs and Referer headers.
    return f"{get_settings().app_base_url.rstrip('/')}/{page}#token={token}"


def _deliver(message: mailer.EmailMessage, user_id: UUID | str) -> bool:
    try:
        mailer.get_provider().send(message)
    except Exception:
        # No address and no link in the log: the user id is enough to follow up.
        log.exception("email not sent", extra={"email_kind": message.kind, "user_id": str(user_id)})
        return False
    log.info("email sent", extra={"email_kind": message.kind, "user_id": str(user_id)})
    return True


# --- Email verification ------------------------------------------------------------------


def is_email_verified(user_id: UUID | str) -> bool:
    with db.global_tx() as conn:
        row = fetch_one(conn, "SELECT email_verified_at FROM users WHERE id = :id", {"id": user_id})
    return bool(row and row["email_verified_at"])


def send_verification_email(user_id: UUID | str) -> str:
    """Mail a fresh confirmation link. Returns "sent", "already_verified" or "failed"."""
    settings = get_settings()
    with db.global_tx() as conn:
        user = fetch_one(conn, "SELECT id, email, full_name, email_verified_at FROM users WHERE id = :id",
                         {"id": user_id})
        if user is None or user["email_verified_at"]:
            return "already_verified"
        token = issue_token(conn, user["id"], VERIFY_EMAIL, user["email"],
                            timedelta(hours=settings.email_verification_ttl_hours))
    message = templates.verification(user["email"], user["full_name"], _link("verify-email", token),
                                     settings.email_verification_ttl_hours)
    return "sent" if _deliver(message, user["id"]) else "failed"


def send_verification_email_quietly(user_id: UUID | str) -> None:
    """Background-task entry point: sign-up must not fail because email is down."""
    try:
        send_verification_email(user_id)
    except Exception:
        log.exception("could not prepare the verification email", extra={"user_id": str(user_id)})


def verify_email(token: str) -> None:
    with db.global_tx() as conn:
        spent = consume_token(conn, token, VERIFY_EMAIL)
        if spent is None:
            raise _invalid_token()
        user = fetch_one(
            conn,
            "UPDATE users SET email_verified_at = coalesce(email_verified_at, now())"
            " WHERE id = :id AND lower(email) = lower(:e) RETURNING id",
            {"id": spent["user_id"], "e": spent["email"]},
        )
        if user is None:  # the address changed after the link was mailed
            raise _invalid_token()
        _audit(conn, user["id"], "auth.email_verified")


# --- Password reset --------------------------------------------------------------------


def request_password_reset(email: str) -> None:
    """Background-task entry point. Mails a reset link when the address has an account and
    does nothing otherwise. Never raises: the caller has already answered."""
    try:
        try:
            email = normalize_email(email)
        except AppError:
            return
        settings = get_settings()
        with db.global_tx() as conn:
            user = fetch_one(conn, "SELECT id, email, full_name FROM users WHERE lower(email) = :e", {"e": email})
            if user is None:
                return
            token = issue_token(conn, user["id"], RESET_PASSWORD, user["email"],
                                timedelta(minutes=settings.password_reset_ttl_minutes))
        _deliver(templates.password_reset(user["email"], user["full_name"], _link("reset-password", token),
                                          settings.password_reset_ttl_minutes), user["id"])
    except Exception:
        log.exception("could not prepare the password reset email")


def reset_password(token: str, password: str) -> None:
    """Set a new password from a reset link and sign the account out everywhere."""
    check_password_policy(password)  # before the token is spent, so a typo does not burn the link
    with db.global_tx() as conn:
        spent = consume_token(conn, token, RESET_PASSWORD)
        if spent is None:
            raise _invalid_token()
        # Using the link proves control of the inbox, so it confirms the address too.
        user = fetch_one(
            conn,
            "UPDATE users SET password_hash = :h, email_verified_at = coalesce(email_verified_at, now())"
            " WHERE id = :id AND lower(email) = lower(:e) RETURNING id, email, full_name",
            {"h": hash_password(password), "id": spent["user_id"], "e": spent["email"]},
        )
        if user is None:
            raise _invalid_token()
        revoked = conn.execute(
            text("UPDATE sessions SET revoked_at = now() WHERE user_id = :uid AND revoked_at IS NULL"),
            {"uid": user["id"]},
        ).rowcount
        conn.execute(
            text("UPDATE user_tokens SET used_at = now()"
                 " WHERE user_id = :uid AND purpose = :p AND used_at IS NULL"),
            {"uid": user["id"], "p": RESET_PASSWORD},
        )
        _audit(conn, user["id"], "auth.password_reset", {"sessions_revoked": revoked})
    _deliver(templates.password_changed(user["email"], user["full_name"],
                                        f"{get_settings().app_base_url.rstrip('/')}/forgot-password"),
             user["id"])


def _audit(conn: Connection, user_id: UUID, action: str, metadata: dict | None = None) -> None:
    """Record against the user's first organization (the audit trail is tenant scoped).
    Last statement of the transaction: it pins the tenant context."""
    member_of = memberships(conn, user_id)
    if not member_of:
        return
    org_id = member_of[0]["organization_id"]
    db.set_tenant(conn, org_id)
    audit.record(conn, org_id=org_id, action=action, resource_type="user", resource_id=user_id,
                 actor_user_id=user_id, metadata=metadata)
