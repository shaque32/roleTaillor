"""Retention: resumes deleted by their owner are erased for good after a grace period.

Deleting a resume only hides it (resumes.archived_at). `purge_due` runs nightly and, once
`resume_retention_days` have passed, erases everything that holds the person's content:
the uploaded and generated files, every version's text and layout, the proposed rewrites,
simulated feedback, embeddings, exports and share links.

What stays is a skeleton with no resume content: the resume, version and workflow rows
(ids, timestamps, status, scores) and the usage, cost and audit records that hang off
them. Billing counts free generations and consumed payments from those rows, so deleting
them would hand back quota that was already used.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Connection, text

from roletailor import db
from roletailor.config import get_settings
from roletailor.services import audit
from roletailor.services.sql import fetch_all, fetch_one
from roletailor.storage import get_storage

log = logging.getLogger(__name__)

PURGED_NAME = "Deleted resume"
_BUSY = ("queued", "running")


@dataclass(frozen=True)
class PurgeSummary:
    purged: int = 0
    skipped: int = 0
    failed: int = 0
    objects_deleted: int = 0


def _purge_resume(conn: Connection, org_id: UUID | str, resume_id: UUID | str,
                  days: int) -> list[tuple[str, str | None]] | None:
    """Erase one resume inside the caller's tenant transaction. Returns the storage
    objects to delete after commit, or None when the resume must be left alone."""
    # Lock order is workflows, then the resume: the same order request paths use.
    conn.execute(
        text("SELECT w.id FROM tailoring_workflows w"
             " JOIN resume_versions v ON v.id = w.source_resume_version_id"
             " WHERE v.resume_id = :rid ORDER BY w.id FOR UPDATE OF w"),
        {"rid": resume_id},
    )
    due = fetch_one(
        conn,
        "SELECT id FROM resumes WHERE id = :rid AND purged_at IS NULL"
        " AND archived_at < now() - make_interval(days => :days) FOR UPDATE",
        {"rid": resume_id, "days": days},
    )
    if due is None:  # restored, already purged, or not old enough after all
        return None
    # Read after the resume lock, so a workflow created just before it is seen.
    workflows = fetch_all(
        conn,
        "SELECT w.id, w.status FROM tailoring_workflows w"
        " JOIN resume_versions v ON v.id = w.source_resume_version_id"
        " WHERE v.resume_id = :rid",
        {"rid": resume_id},
    )
    if any(w["status"] in _BUSY for w in workflows):
        return None  # a run is in flight; the next nightly pass picks this resume up
    p = {"rid": resume_id}
    versions = "(SELECT id FROM resume_versions WHERE resume_id = :rid)"
    owned_workflows = f"(SELECT id FROM tailoring_workflows WHERE source_resume_version_id IN {versions})"
    generated = f"(SELECT id FROM generated_resumes WHERE workflow_id IN {owned_workflows})"

    file_ids = [r["id"] for r in fetch_all(
        conn,
        f"SELECT source_file_id AS id FROM resume_versions WHERE resume_id = :rid"
        f" AND source_file_id IS NOT NULL"
        f" UNION SELECT file_id FROM resume_exports WHERE resume_version_id IN {versions}",
        p,
    )]

    for statement in (
        f"DELETE FROM embeddings WHERE resume_version_id IN {versions}",
        f"DELETE FROM resume_share_links WHERE export_id IN"
        f" (SELECT id FROM resume_exports WHERE resume_version_id IN {versions})",
        f"DELETE FROM resume_exports WHERE resume_version_id IN {versions}",
        f"UPDATE applications SET resume_version_id = NULL WHERE resume_version_id IN {versions}",
        f"UPDATE resume_changes SET prior_text = NULL, proposed_text = NULL, reason = NULL,"
        f" prioritized_keywords = '{{}}' WHERE generated_resume_id IN {generated}",
        f"UPDATE generated_resumes SET simulated_feedback = NULL WHERE id IN {generated}",
        f"UPDATE validation_results SET details = '{{}}' WHERE workflow_id IN {owned_workflows}",
        f"UPDATE tailoring_workflows SET draft_state = '{{}}' WHERE id IN {owned_workflows}",
        "UPDATE resume_versions SET content = '{}', layout_metadata = '{}',"
        " extraction_findings = '[]', source_file_id = NULL WHERE resume_id = :rid",
        "UPDATE resumes SET name = :name, purged_at = now() WHERE id = :rid",
    ):
        conn.execute(text(statement), {**p, "name": PURGED_NAME})

    objects: list[tuple[str, str | None]] = []
    if file_ids:
        # A file row goes only when nothing else points at it any more.
        objects = [(r["object_key"], r["object_version"]) for r in fetch_all(
            conn,
            "DELETE FROM stored_files f WHERE f.id = ANY(:ids)"
            " AND NOT EXISTS (SELECT 1 FROM resume_versions v WHERE v.source_file_id = f.id)"
            " AND NOT EXISTS (SELECT 1 FROM resume_exports e WHERE e.file_id = f.id)"
            " RETURNING f.object_key, f.object_version",
            {"ids": file_ids},
        )]
    audit.record(
        conn, org_id=org_id, action="resume.purge", resource_type="resume", resource_id=resume_id,
        metadata={"retention_days": days, "versions": len(fetch_all(
            conn, "SELECT 1 FROM resume_versions WHERE resume_id = :rid", p)),
            "workflows": len(workflows), "files": len(objects)},
    )
    return objects


def purge_due(*, limit: int | None = None) -> PurgeSummary:
    """Erase every deleted resume whose retention period has passed, oldest first.
    Each resume is its own transaction, so one failure does not hold back the rest."""
    settings = get_settings()
    days = settings.resume_retention_days
    with db.global_tx() as conn:
        due = fetch_all(
            conn,
            "SELECT organization_id, resume_id FROM"
            " roletailor.resumes_due_for_purge(make_interval(days => :days), :limit)",
            {"days": days, "limit": limit or settings.retention_purge_batch_size},
        )
    storage = get_storage()
    purged = skipped = failed = deleted = 0
    for row in due:
        try:
            with db.tenant_tx(row["organization_id"]) as conn:
                objects = _purge_resume(conn, row["organization_id"], row["resume_id"], days)
        except Exception:
            failed += 1
            log.exception("could not purge resume", extra={"resume_id": str(row["resume_id"])})
            continue
        if objects is None:
            skipped += 1
            continue
        purged += 1
        for key, version in objects:
            try:
                storage.delete(key, version)
                deleted += 1
            except Exception:  # the rows are gone; leftovers are swept by bucket lifecycle rules
                log.exception("could not delete stored object", extra={"object_key": key})
    summary = PurgeSummary(purged, skipped, failed, deleted)
    log.info("retention.purge", extra={"audit_action": "retention.purge", "due": len(due),
                                       "purged": purged, "skipped": skipped, "failed": failed,
                                       "objects_deleted": deleted})
    return summary
