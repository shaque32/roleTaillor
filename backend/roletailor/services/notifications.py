"""In-app notifications (notifications table, channel 'in_app')."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Connection, text

from roletailor import db
from roletailor.services.auth import Principal
from roletailor.services.errors import not_found
from roletailor.services.sql import fetch_all, fetch_one, jsonb

COLUMNS = "id, kind, payload, created_at, read_at"


def notify_admins(conn: Connection, kind: str, payload: dict) -> None:
    """Notify every owner and admin of the current organization."""
    conn.execute(
        text(
            "INSERT INTO notifications (organization_id, user_id, channel, kind, payload)"
            " SELECT organization_id, user_id, 'in_app', :kind, CAST(:payload AS jsonb)"
            " FROM organization_members WHERE role IN ('owner', 'admin')"
        ),
        {"kind": kind, "payload": jsonb(payload)},
    )


def list_for(principal: Principal) -> list[dict]:
    with db.tenant_tx(principal.org_id) as conn:
        return fetch_all(
            conn,
            f"SELECT {COLUMNS} FROM notifications WHERE user_id = :uid AND channel = 'in_app'"
            " ORDER BY created_at DESC LIMIT 100",
            {"uid": principal.user_id},
        )


def mark_read(principal: Principal, notification_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        row = fetch_one(
            conn,
            "UPDATE notifications SET read_at = coalesce(read_at, now())"
            f" WHERE id = :id AND user_id = :uid RETURNING {COLUMNS}",
            {"id": notification_id, "uid": principal.user_id},
        )
    if row is None:
        raise not_found("Notification")
    return row
