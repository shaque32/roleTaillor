"""Registration, password login and bearer sessions.

Login is split into `_verify_password` (first factor) and `_issue_session`, so a
second factor can be inserted between them without touching session handling:
`login` would return a pending challenge instead of a token when MFA is enrolled.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import Connection, text

from roletailor import db
from roletailor.config import get_settings
from roletailor.services import audit
from roletailor.services.errors import AppError
from roletailor.services.sql import fetch_all, fetch_one

_hasher = PasswordHasher()
# Verified when the email is unknown so both paths cost one argon2 verification.
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 10

USER_COLUMNS = (
    "id, email, full_name, address, contact_number, linkedin_url, preferred_page_limit,"
    " industry_focus, resume_tone, ats_preference, technical_depth, preferred_template_id,"
    " created_at, email_verified_at"
)


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    session_id: UUID
    org_id: UUID
    role: str


@dataclass(frozen=True)
class AuthResult:
    token: str
    expires_at: datetime
    user: dict
    organization: dict


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL_RE.match(email) or len(email) > 320:
        raise AppError(422, "invalid_email", "Enter a valid email address.")
    return email


def check_password_policy(password: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= 256:
        raise AppError(
            422, "weak_password", f"Passwords need at least {MIN_PASSWORD_LENGTH} characters."
        )


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def memberships(conn: Connection, user_id: UUID | str) -> list[dict]:
    """(organization_id, role) pairs, oldest first. Works without tenant context."""
    return fetch_all(
        conn,
        "SELECT organization_id, role FROM roletailor.user_memberships(:uid)",
        {"uid": str(user_id)},
    )


def _issue_session(conn: Connection, user_id: UUID, device_label: str | None) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=get_settings().session_ttl_hours)
    conn.execute(
        text(
            "INSERT INTO sessions (user_id, token_hash, device_label, created_at, expires_at)"
            " VALUES (:uid, :hash, :label, :now, :exp)"
        ),
        {
            "uid": user_id,
            "hash": hash_token(token),
            "label": (device_label or "")[:200] or None,
            "now": now,
            "exp": expires_at,
        },
    )
    return token, expires_at


def _organization(conn: Connection, org_id: UUID, role: str) -> dict:
    org = fetch_one(conn, "SELECT id, name FROM organizations WHERE id = :id", {"id": org_id})
    assert org is not None, "membership without a visible organization"
    return {**org, "role": role}


def register(email: str, password: str, full_name: str, device_label: str | None) -> AuthResult:
    email = normalize_email(email)
    check_password_policy(password)
    org_id = uuid4()
    with db.global_tx() as conn:
        if fetch_one(conn, "SELECT 1 FROM users WHERE lower(email) = :e", {"e": email}):
            raise AppError(409, "email_taken", "An account with this email already exists.")
        user = fetch_one(
            conn,
            f"INSERT INTO users (email, password_hash, full_name) VALUES (:e, :h, :n)"
            f" RETURNING {USER_COLUMNS}",
            {"e": email, "h": _hasher.hash(password), "n": full_name.strip()},
        )
        assert user is not None
        # The organization is new, so pin the transaction to its id before inserting;
        # the RLS policy doubles as the WITH CHECK for these rows.
        db.set_tenant(conn, org_id)
        conn.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
            {"id": org_id, "name": f"{full_name.strip() or email}'s workspace"},
        )
        conn.execute(
            text(
                "INSERT INTO organization_members (organization_id, user_id, role)"
                " VALUES (:org, :uid, 'owner')"
            ),
            {"org": org_id, "uid": user["id"]},
        )
        token, expires_at = _issue_session(conn, user["id"], device_label)
        audit.record(
            conn, org_id=org_id, action="auth.register", resource_type="user",
            resource_id=user["id"], actor_user_id=user["id"],
        )
        organization = _organization(conn, org_id, "owner")
    return AuthResult(token=token, expires_at=expires_at, user=user, organization=organization)


def _verify_password(conn: Connection, email: str, password: str) -> dict | None:
    # The row lock makes a login and a password reset for the same account take turns:
    # a login that checked the old password commits its session before the reset revokes
    # sessions, or waits and then reads the new hash. NO KEY UPDATE conflicts with the
    # reset's UPDATE but not with inserts that reference the user.
    row = fetch_one(
        conn, "SELECT id, password_hash FROM users WHERE lower(email) = :e FOR NO KEY UPDATE", {"e": email}
    )
    stored = row["password_hash"] if row and row["password_hash"] else _DUMMY_HASH
    try:
        _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return None
    if row is None or not row["password_hash"]:
        return None
    if _hasher.check_needs_rehash(stored):
        conn.execute(
            text("UPDATE users SET password_hash = :h WHERE id = :id"),
            {"h": _hasher.hash(password), "id": row["id"]},
        )
    return row


def login(email: str, password: str, device_label: str | None) -> AuthResult:
    invalid = AppError(401, "invalid_credentials", "Email or password is incorrect.")
    try:
        email = normalize_email(email)
    except AppError:
        raise invalid from None
    with db.global_tx() as conn:
        row = _verify_password(conn, email, password)
        if row is None:
            raise invalid
        member_of = memberships(conn, row["id"])
        if not member_of:
            raise AppError(403, "no_organization", "This account has no workspace.")
        # Second-factor check goes here once MFA is enrolled for the user.
        token, expires_at = _issue_session(conn, row["id"], device_label)
        user = fetch_one(conn, f"SELECT {USER_COLUMNS} FROM users WHERE id = :id", {"id": row["id"]})
        primary = member_of[0]
        db.set_tenant(conn, primary["organization_id"])
        audit.record(
            conn, org_id=primary["organization_id"], action="auth.login",
            resource_type="session", actor_user_id=row["id"],
            metadata={"device_label": (device_label or "")[:200]},
        )
        organization = _organization(conn, primary["organization_id"], primary["role"])
    assert user is not None
    return AuthResult(token=token, expires_at=expires_at, user=user, organization=organization)


def authenticate(token: str, requested_org: UUID | None = None) -> Principal | None:
    """Resolve a bearer token to a principal in one of the user's organizations
    (the requested one when given and the user belongs to it, else the oldest)."""
    with db.global_tx() as conn:
        session = fetch_one(
            conn,
            "SELECT id, user_id FROM sessions WHERE token_hash = :h"
            " AND revoked_at IS NULL AND expires_at > now()",
            {"h": hash_token(token)},
        )
        if session is None:
            return None
        member_of = memberships(conn, session["user_id"])
    if requested_org is not None:
        member_of = [m for m in member_of if m["organization_id"] == requested_org]
    if not member_of:
        return None
    return Principal(
        user_id=session["user_id"],
        session_id=session["id"],
        org_id=member_of[0]["organization_id"],
        role=member_of[0]["role"],
    )


def logout(principal: Principal) -> None:
    with db.global_tx() as conn:
        conn.execute(
            text("UPDATE sessions SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL"),
            {"id": principal.session_id},
        )
