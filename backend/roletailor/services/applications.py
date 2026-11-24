"""Job application tracker (applications, per user)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text

from roletailor import db
from roletailor.services.auth import Principal
from roletailor.services.errors import not_found
from roletailor.services.sql import fetch_all, fetch_one

COLUMNS = (
    "id, company, role_title, status, applied_at, reminder_at, notes, job_posting_id,"
    " resume_version_id, created_at"
)
FIELDS = ("company", "role_title", "status", "applied_at", "reminder_at", "notes",
          "job_posting_id", "resume_version_id")


def list_applications(principal: Principal) -> list[dict]:
    with db.tenant_tx(principal.org_id) as conn:
        return fetch_all(
            conn, f"SELECT {COLUMNS} FROM applications WHERE user_id = :uid ORDER BY created_at DESC",
            {"uid": principal.user_id},
        )


def create(principal: Principal, data: dict[str, Any]) -> dict:
    values = {k: data.get(k) for k in FIELDS}
    values["status"] = values["status"] or "saved"
    with db.tenant_tx(principal.org_id) as conn:
        row = fetch_one(
            conn,
            f"INSERT INTO applications (organization_id, user_id, {', '.join(FIELDS)})"
            f" VALUES (:org, :uid, {', '.join(':' + f for f in FIELDS)}) RETURNING {COLUMNS}",
            {**values, "org": principal.org_id, "uid": principal.user_id},
        )
    assert row is not None
    return row


def get(principal: Principal, application_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        row = fetch_one(
            conn, f"SELECT {COLUMNS} FROM applications WHERE id = :id AND user_id = :uid",
            {"id": application_id, "uid": principal.user_id},
        )
    if row is None:
        raise not_found("Application")
    return row


def update(principal: Principal, application_id: UUID, changes: dict[str, Any]) -> dict:
    fields = {k: v for k, v in changes.items() if k in FIELDS}
    if not fields:
        return get(principal, application_id)
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    with db.tenant_tx(principal.org_id) as conn:
        row = fetch_one(
            conn,
            f"UPDATE applications SET {assignments} WHERE id = :id AND user_id = :uid RETURNING {COLUMNS}",
            {**fields, "id": application_id, "uid": principal.user_id},
        )
    if row is None:
        raise not_found("Application")
    return row


def delete(principal: Principal, application_id: UUID) -> None:
    with db.tenant_tx(principal.org_id) as conn:
        deleted = conn.execute(
            text("DELETE FROM applications WHERE id = :id AND user_id = :uid"),
            {"id": application_id, "uid": principal.user_id},
        ).rowcount
    if not deleted:
        raise not_found("Application")
