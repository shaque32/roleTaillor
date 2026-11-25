"""Reviewing generated resumes: change decisions, approval, exports and share links."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import Connection

from roletailor import db
from roletailor.config import get_settings
from roletailor.services import audit, files, rendering, reports, resumes
from roletailor.services.auth import Principal, hash_token
from roletailor.services.errors import AppError, not_found
from roletailor.services.sql import fetch_all, fetch_one
from roletailor.services.workflows import CHANGE_COLUMNS, GENERATED_COLUMNS
from roletailor.storage import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE

ExportKind = Literal["docx", "pdf", "ats_report", "feedback_report"]


def _get_generated(conn: Connection, principal: Principal, generated_id: UUID) -> dict:
    row = fetch_one(
        conn,
        f"SELECT {', '.join('g.' + c.strip() for c in GENERATED_COLUMNS.split(','))}"
        " FROM generated_resumes g JOIN tailoring_workflows w ON w.id = g.workflow_id"
        " WHERE g.id = :id AND w.requested_by = :uid",
        {"id": generated_id, "uid": principal.user_id},
    )
    if row is None:
        raise not_found("Generated resume")
    return row


def decide_change(principal: Principal, generated_id: UUID, change_id: UUID,
                  decision: Literal["accepted", "rejected", "pending"]) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        _get_generated(conn, principal, generated_id)
        row = fetch_one(
            conn,
            "UPDATE resume_changes SET decision = :d,"
            " decided_at = CASE WHEN :d = 'pending' THEN NULL ELSE now() END"
            f" WHERE id = :id AND generated_resume_id = :g RETURNING {CHANGE_COLUMNS}",
            {"d": decision, "id": change_id, "g": generated_id},
        )
    if row is None:
        raise not_found("Change")
    return row


def approve(principal: Principal, generated_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        _get_generated(conn, principal, generated_id)
        row = fetch_one(
            conn,
            "UPDATE generated_resumes SET approved_at = coalesce(approved_at, now())"
            f" WHERE id = :id RETURNING {GENERATED_COLUMNS}",
            {"id": generated_id},
        )
        assert row is not None
        audit.record(
            conn, org_id=principal.org_id, action="generated.approved",
            resource_type="generated_resume", resource_id=generated_id, actor_user_id=principal.user_id,
        )
    return row


def _reviewed_edits(conn: Connection, generated: dict) -> tuple[rendering.Base, dict[str, str], dict | None]:
    """The parent version and every change that was not rejected."""
    version = resumes.get_version(conn, generated["resume_version_id"])
    parent = resumes.get_version(conn, version["parent_version_id"])
    changes = fetch_all(
        conn,
        "SELECT block_path, proposed_text FROM resume_changes"
        " WHERE generated_resume_id = :g AND decision <> 'rejected'",
        {"g": generated["id"]},
    )
    edits = {c["block_path"]: c["proposed_text"] for c in changes if c["proposed_text"] is not None}
    structure = (version["content"] or {}).get("structure")
    return rendering.load_base(conn, parent), edits, structure


def _reviewed_docx(conn: Connection, generated: dict) -> bytes:
    return rendering.render_with_edits(*_reviewed_edits(conn, generated))


def _reviewed_pdf(conn: Connection, generated: dict) -> bytes:
    """PDF sources keep their original layout when the edits fit; others convert the DOCX."""
    return rendering.render_pdf(*_reviewed_edits(conn, generated))


def _export_bytes(conn: Connection, generated: dict, kind: ExportKind) -> tuple[bytes, str, str]:
    feedback = generated["simulated_feedback"] or {}
    if kind == "docx":
        return _reviewed_docx(conn, generated), DOCX_MEDIA_TYPE, "tailored-resume"
    if kind == "pdf":
        try:
            pdf = _reviewed_pdf(conn, generated)
        except Exception as exc:
            raise AppError(503, "pdf_unavailable", "PDF export is unavailable. Download the DOCX instead.") from exc
        return pdf, PDF_MEDIA_TYPE, "tailored-resume"
    if kind == "ats_report":
        changes = fetch_all(
            conn, "SELECT prioritized_keywords FROM resume_changes WHERE generated_resume_id = :g"
            " AND decision <> 'rejected'", {"g": generated["id"]},
        )
        scores = {k: generated[f"{k}_score"] for k in ("ats", "job_alignment", "keyword_relevance", "formatting")}
        data = reports.ats_report(scores, feedback.get("scores_before"), feedback.get("gaps", []), changes)
        return data, DOCX_MEDIA_TYPE, "ats-report"
    if not feedback.get("overall"):
        raise AppError(409, "feedback_unavailable", "This generation has no simulated feedback.")
    return reports.feedback_report(feedback), DOCX_MEDIA_TYPE, "feedback-report"


def create_export(principal: Principal, generated_id: UUID, kind: ExportKind) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        generated = _get_generated(conn, principal, generated_id)
        data, media_type, name = _export_bytes(conn, generated, kind)
        stored = files.store(conn, principal.org_id, data, media_type=media_type, filename=name,
                             category="exports")
        export = fetch_one(
            conn,
            "INSERT INTO resume_exports (organization_id, resume_version_id, file_id, kind)"
            " VALUES (:org, :v, :f, :k) RETURNING id",
            {"org": principal.org_id, "v": generated["resume_version_id"], "f": stored["id"], "k": kind},
        )
        assert export is not None
        audit.record(
            conn, org_id=principal.org_id, action="export.created", resource_type="resume_export",
            resource_id=export["id"], actor_user_id=principal.user_id,
            metadata={"kind": kind, "generated_resume_id": str(generated_id)},
        )
    url, expires_at = files.signed_url(stored)
    return {"export_id": export["id"], "download_url": url, "expires_at": expires_at}


def _owned_export_file(conn: Connection, principal: Principal | None, export_id: UUID) -> dict:
    sql = (
        "SELECT e.file_id FROM resume_exports e"
        " JOIN resume_versions v ON v.id = e.resume_version_id"
        " JOIN resumes r ON r.id = v.resume_id WHERE e.id = :id"
    )
    params: dict = {"id": export_id}
    if principal is not None:
        sql += " AND r.owner_user_id = :uid"
        params["uid"] = principal.user_id
    row = fetch_one(conn, sql, params)
    if row is None:
        raise not_found("Export")
    return files.get_clean(conn, row["file_id"])


def share(principal: Principal, export_id: UUID, expires_in_hours: int) -> dict:
    max_hours = get_settings().share_link_max_hours
    if not 1 <= expires_in_hours <= max_hours:
        raise AppError(422, "invalid_expiry", f"Share links last between 1 and {max_hours} hours.")
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=expires_in_hours)
    with db.tenant_tx(principal.org_id) as conn:
        _owned_export_file(conn, principal, export_id)
        link = fetch_one(
            conn,
            "INSERT INTO resume_share_links (organization_id, export_id, token_hash, expires_at)"
            " VALUES (:org, :e, :h, :exp) RETURNING id",
            {"org": principal.org_id, "e": export_id, "h": hash_token(token), "exp": expires_at},
        )
        assert link is not None
        audit.record(
            conn, org_id=principal.org_id, action="export.shared", resource_type="resume_share_link",
            resource_id=link["id"], actor_user_id=principal.user_id,
            metadata={"export_id": str(export_id), "expires_at": expires_at.isoformat()},
        )
    return {"url": f"{get_settings().api_base_url}/v1/share/{token}", "expires_at": expires_at}


def resolve_share(token: str) -> str:
    """Signed download URL for an active share link, or 404."""
    with db.global_tx() as conn:
        link = fetch_one(
            conn, "SELECT organization_id, export_id FROM roletailor.resolve_share_link(:h)",
            {"h": hash_token(token)},
        )
        if link is None:
            raise not_found("Share link")
        db.set_tenant(conn, link["organization_id"])
        stored = _owned_export_file(conn, None, link["export_id"])
    return files.signed_url(stored)[0]
