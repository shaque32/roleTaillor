"""Append-only audit trail for sensitive actions (audit_logs, tenant scoped)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from roletailor.logging_setup import correlation_id
from roletailor.services.sql import jsonb


def record(
    conn: Connection,
    *,
    org_id: UUID | str,
    action: str,
    resource_type: str,
    resource_id: UUID | str | None = None,
    actor_user_id: UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO audit_logs (organization_id, actor_user_id, action, resource_type,"
            " resource_id, correlation_id, metadata)"
            " VALUES (:org, :actor, :action, :rtype, :rid, :cid, CAST(:meta AS jsonb))"
        ),
        {
            "org": str(org_id),
            "actor": str(actor_user_id) if actor_user_id else None,
            "action": action,
            "rtype": resource_type,
            "rid": str(resource_id) if resource_id else None,
            "cid": correlation_id.get(),
            "meta": jsonb(metadata or {}),
        },
    )
