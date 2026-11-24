"""User profile, tailoring preferences and consent records (global tables)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection

from roletailor import db
from roletailor.services.auth import USER_COLUMNS
from roletailor.services.errors import AppError, not_found
from roletailor.services.sql import fetch_one, jsonb

AI_PROCESSING = "ai_processing"
CONSENT_PURPOSES = frozenset({AI_PROCESSING})
PROFILE_FIELDS = frozenset({
    "full_name", "address", "contact_number", "linkedin_url", "preferred_page_limit",
    "industry_focus", "resume_tone", "ats_preference", "technical_depth",
    "preferred_template_id",
})


def latest_consent(conn: Connection, user_id: UUID | str, purpose: str) -> bool:
    row = fetch_one(
        conn,
        "SELECT granted FROM user_consents WHERE user_id = :uid AND purpose = :p"
        " ORDER BY recorded_at DESC, id DESC LIMIT 1",
        {"uid": str(user_id), "p": purpose},
    )
    return bool(row and row["granted"])


def _with_consents(conn: Connection, user: dict) -> dict:
    return {**user, "consents": {AI_PROCESSING: latest_consent(conn, user["id"], AI_PROCESSING)}}


def get_profile(user_id: UUID) -> dict:
    with db.global_tx() as conn:
        user = fetch_one(conn, f"SELECT {USER_COLUMNS} FROM users WHERE id = :id", {"id": user_id})
        if user is None:
            raise not_found("User")
        return _with_consents(conn, user)


def update_profile(user_id: UUID, changes: dict[str, Any]) -> dict:
    fields = {k: v for k, v in changes.items() if k in PROFILE_FIELDS}
    if not fields:
        return get_profile(user_id)
    if "preferred_template_id" in fields and fields["preferred_template_id"] is not None:
        fields["preferred_template_id"] = str(fields["preferred_template_id"])
    assignments = ", ".join(
        f"{k} = CAST(:{k} AS jsonb)" if k == "address" else f"{k} = :{k}" for k in fields
    )
    params = {**fields, "id": user_id}
    if "address" in params:
        params["address"] = jsonb(params["address"]) if params["address"] is not None else None
    with db.global_tx() as conn:
        user = fetch_one(
            conn, f"UPDATE users SET {assignments} WHERE id = :id RETURNING {USER_COLUMNS}", params
        )
        if user is None:
            raise not_found("User")
        return _with_consents(conn, user)


def record_consent(user_id: UUID, purpose: str, policy_version: str, granted: bool) -> dict:
    if purpose not in CONSENT_PURPOSES:
        raise AppError(422, "unknown_consent_purpose", f"Unknown consent purpose {purpose!r}.")
    with db.global_tx() as conn:
        row = fetch_one(
            conn,
            "INSERT INTO user_consents (user_id, purpose, policy_version, granted)"
            " VALUES (:uid, :p, :v, :g)"
            " RETURNING id, purpose, policy_version, granted, recorded_at",
            {"uid": user_id, "p": purpose, "v": policy_version, "g": granted},
        )
    assert row is not None
    return row


def has_ai_consent(user_id: UUID) -> bool:
    with db.global_tx() as conn:
        return latest_consent(conn, user_id, AI_PROCESSING)


def preferences(conn: Connection, user_id: UUID | str) -> dict:
    row = fetch_one(
        conn,
        "SELECT preferred_page_limit, industry_focus, resume_tone, ats_preference,"
        " technical_depth FROM users WHERE id = :id",
        {"id": str(user_id)},
    )
    if row is None:
        raise not_found("User")
    return row

