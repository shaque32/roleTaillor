"""Data subject rights: full data export and account deletion."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import Connection, text

from roletailor import db
from roletailor.services import audit
from roletailor.services.auth import USER_COLUMNS, Principal, memberships
from roletailor.services.errors import AppError
from roletailor.services.sql import fetch_all, fetch_one
from roletailor.storage import get_storage

log = logging.getLogger(__name__)

# Exported per organization. Embeddings and AI telemetry are derived data, not the user's.
_EXPORT_TABLES = (
    "resumes", "resume_versions", "job_postings", "tailoring_workflows", "generated_resumes",
    "resume_changes", "resume_exports", "applications", "subscriptions", "payments",
    "usage_tracking", "notifications",
)
# Children before parents, so foreign keys hold at every step.
_PURGE_ORDER = (
    "validation_results", "ai_metrics", "embeddings", "resume_changes", "usage_tracking",
    "resume_share_links", "resume_exports", "generated_resumes", "applications",
    "tailoring_workflows", "payments", "subscriptions", "resume_versions", "resumes",
    "job_postings", "notifications", "audit_logs", "stored_files", "organization_members",
)


def export_data(principal: Principal) -> dict:
    with db.global_tx() as conn:
        user = fetch_one(conn, f"SELECT {USER_COLUMNS} FROM users WHERE id = :id", {"id": principal.user_id})
        consents = fetch_all(
            conn, "SELECT purpose, policy_version, granted, recorded_at FROM user_consents"
            " WHERE user_id = :id ORDER BY recorded_at", {"id": principal.user_id},
        )
        sessions = fetch_all(
            conn, "SELECT device_label, created_at, expires_at, revoked_at FROM sessions"
            " WHERE user_id = :id ORDER BY created_at", {"id": principal.user_id},
        )
        member_of = memberships(conn, principal.user_id)
    organizations = []
    for membership in member_of:
        with db.tenant_tx(membership["organization_id"]) as conn:
            org = fetch_one(conn, "SELECT id, name, created_at FROM organizations WHERE id = :id",
                            {"id": membership["organization_id"]})
            data = {table: fetch_all(conn, f"SELECT * FROM {table}") for table in _EXPORT_TABLES}
            audit.record(conn, org_id=membership["organization_id"], action="account.data_export",
                         resource_type="user", resource_id=principal.user_id, actor_user_id=principal.user_id)
        organizations.append({"organization": org, "role": membership["role"], "data": data})
    return {"user": user, "consents": consents, "sessions": sessions, "organizations": organizations}


def _purge_organization(conn: Connection, org_id: UUID) -> list[tuple[str, str | None]]:
    """Delete every row of the current organization; returns its stored objects."""
    objects = [(r["object_key"], r["object_version"])
               for r in fetch_all(conn, "SELECT object_key, object_version FROM stored_files")]
    for table in _PURGE_ORDER:
        conn.execute(text(f"DELETE FROM {table}"))  # RLS limits each delete to this tenant
    conn.execute(text("DELETE FROM organizations WHERE id = :id"), {"id": org_id})
    return objects


def delete_account(principal: Principal) -> None:
    """Right to delete. Organizations the user is the only member of are erased with all
    their data and files; shared organizations must be handed over first."""
    with db.global_tx() as conn:
        member_of = memberships(conn, principal.user_id)
        objects: list[tuple[str, str | None]] = []
        purged: list[str] = []
        for membership in member_of:
            org_id = membership["organization_id"]
            db.set_tenant(conn, org_id)
            members = conn.execute(text("SELECT count(*) FROM organization_members")).scalar_one()
            if members > 1:
                raise AppError(409, "shared_organization",
                               "Transfer or leave your shared workspaces before deleting your account.",
                               {"organization_id": str(org_id)})
            objects += _purge_organization(conn, org_id)
            purged.append(str(org_id))
        conn.execute(text("SELECT set_config('app.organization_id', '', true)"))
        # Sessions and consents cascade with the user row.
        conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": principal.user_id})
    storage = get_storage()
    for key, version in objects:
        try:
            storage.delete(key, version)
        except Exception:  # the rows are gone; leftovers are swept by bucket lifecycle rules
            log.exception("could not delete stored object", extra={"object_key": key})
    # The tenant audit trail was erased with the tenant, so the deletion itself is
    # recorded in the structured log stream (ids only, no personal data).
    log.info("account.deleted", extra={"audit_action": "account.deleted", "user_id": str(principal.user_id),
                                       "organizations_purged": purged, "objects_deleted": len(objects)})
