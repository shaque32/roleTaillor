"""Resumes and their immutable versions (uploads, guided creation, restores)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from roletailor import db
from roletailor.config import get_settings
from roletailor.documents.model import ParsedDocument
from roletailor.logging_setup import correlation_id
from roletailor.services import audit, files, guided
from roletailor.services.auth import Principal
from roletailor.services.errors import AppError, not_found
from roletailor.services.sql import fetch_all, fetch_one, jsonb
from roletailor.storage import DOCX_MEDIA_TYPE

log = logging.getLogger(__name__)

_PROCESSING_FIELDS = ("processing_status", "processing_error", "processing_started_at",
                      "processing_file_id")
RESUME_COLUMNS = "id, name, origin, created_at, archived_at, " + ", ".join(_PROCESSING_FIELDS)
# User-facing text for each processing error code (stored as the bare code).
PROCESSING_MESSAGES = {
    "ocr_no_text": "We could not find any text in this scan. Try a clearer scan, a DOCX, or paste the text.",
    "ocr_failed": "We could not read this scan. Try again, or upload a DOCX or paste the text.",
    "ocr_timeout": "Reading this scan took too long. Try again, or upload a DOCX or paste the text.",
    "ocr_unavailable": "We could not start reading this scan. Try again in a moment.",
}
_VERSION_FIELDS = (
    "id", "resume_id", "version_number", "parent_version_id", "source_file_id", "content",
    "layout_metadata", "extraction_findings", "created_at",
)
VERSION_COLUMNS = ", ".join(_VERSION_FIELDS)


def effective_processing(row: dict) -> tuple[str, str | None] | None:
    """(status, error code) of a resume row, or None when it is ready. A row still
    `processing` after `ocr_stale_after_seconds` (a lost task) reads as a timed-out failure;
    nothing is written."""
    status = row.get("processing_status")
    if status is None:
        return None
    if status == "processing":
        started = row.get("processing_started_at")
        stale_after = get_settings().ocr_stale_after_seconds
        if started is not None and (datetime.now(UTC) - started).total_seconds() > stale_after:
            return "failed", "ocr_timeout"
        return "processing", None
    return "failed", row.get("processing_error") or "ocr_failed"


def processing_out(row: dict) -> dict | None:
    """API `processing` object of a resume row: None when ready."""
    state = effective_processing(row)
    if state is None:
        return None
    status, code = state
    error = None
    if code is not None:
        error = {"code": code, "message": PROCESSING_MESSAGES.get(code, PROCESSING_MESSAGES["ocr_failed"])}
    return {"status": status, "error": error, "started_at": row.get("processing_started_at")}


def resume_out(row: dict) -> dict:
    """API shape of a resumes row: the processing columns become one `processing` key."""
    out = {k: v for k, v in row.items() if k not in _PROCESSING_FIELDS}
    out["processing"] = processing_out(row)
    return out


def version_out(row: dict) -> dict:
    """API shape of a resume_versions row."""
    content = row["content"] or {}
    return {
        "id": row["id"],
        "resume_id": row["resume_id"],
        "version_number": row["version_number"],
        "parent_version_id": row["parent_version_id"],
        "source_file_id": row["source_file_id"],
        "source_format": content.get("source_format"),
        "blocks": content.get("blocks", []),
        # How a generated version was rendered: docx_in_place, pdf_in_place or template.
        "render": content.get("render"),
        "findings": row["extraction_findings"],
        "layout_metadata": row["layout_metadata"],
        "created_at": row["created_at"],
    }


def document_content(doc: ParsedDocument, structure: dict | None = None) -> dict[str, Any]:
    return {
        "source_format": doc.source_format,
        "blocks": [b.model_dump() for b in doc.blocks],
        "structure": structure,
        # Text PDFs whose block ids address the stored file can be edited in place.
        "pdf_in_place": doc.source_format == "pdf" and doc.supports_in_place_edit,
    }


def parse_document(data: bytes, media_type: str) -> ParsedDocument:
    from roletailor import documents

    try:
        if media_type == DOCX_MEDIA_TYPE:
            return documents.read_docx(data)
        return documents.read_pdf_text(data)
    except Exception as exc:  # parser errors are user-facing, not server faults
        raise AppError(
            422, "resume_unreadable",
            "We could not read this file. Try another export of your resume.",
        ) from exc


def parse_upload(data: bytes, media_type: str) -> ParsedDocument:
    """Parse an untrusted upload in the resource-limited child process (documents.sandbox)."""
    from roletailor.config import get_settings
    from roletailor.documents import sandbox

    settings = get_settings()
    try:
        return sandbox.parse_untrusted(
            data, "docx" if media_type == DOCX_MEDIA_TYPE else "pdf",
            timeout=settings.parse_timeout_seconds, memory_mb=settings.parse_memory_limit_mb,
            cpu_seconds=settings.parse_cpu_seconds, max_pages=settings.max_resume_pdf_pages,
            max_blocks=settings.max_resume_blocks,
        )
    except sandbox.DocumentRejected as exc:
        raise AppError(422, "resume_too_large", str(exc)) from exc
    except sandbox.ParserBusy as exc:
        raise AppError(503, "parser_busy", "We are reading a lot of resumes right now. "
                       "Try again in a moment.", {"retry_after": 15}) from exc
    except Exception as exc:  # crashes, limits and unreadable files are user-facing, not faults
        raise AppError(
            422, "resume_unreadable",
            "We could not read this file. Try another export of your resume.",
        ) from exc


# --------------------------------------------------------------------------
# Repository helpers (callers own the transaction)
# --------------------------------------------------------------------------


def get_owned_resume(conn: Connection, principal: Principal, resume_id: UUID, *, lock=False) -> dict:
    row = fetch_one(
        conn,
        f"SELECT {RESUME_COLUMNS} FROM resumes WHERE id = :id AND owner_user_id = :uid"
        + (" FOR UPDATE" if lock else ""),
        {"id": resume_id, "uid": principal.user_id},
    )
    if row is None:
        raise not_found("Resume")
    return row


def get_version(conn: Connection, version_id: UUID | str) -> dict:
    row = fetch_one(
        conn, f"SELECT {VERSION_COLUMNS} FROM resume_versions WHERE id = :id", {"id": version_id}
    )
    if row is None:
        raise not_found("Resume version")
    return row


def get_owned_version(conn: Connection, principal: Principal, version_id: UUID) -> dict:
    row = fetch_one(
        conn,
        f"SELECT {', '.join('v.' + f for f in _VERSION_FIELDS)} FROM resume_versions v"
        " JOIN resumes r ON r.id = v.resume_id"
        " WHERE v.id = :id AND r.owner_user_id = :uid",
        {"id": version_id, "uid": principal.user_id},
    )
    if row is None:
        raise not_found("Resume version")
    return row


def insert_version(
    conn: Connection,
    resume_id: UUID | str,
    *,
    content: dict,
    layout_metadata: dict,
    findings: list,
    source_file_id: UUID | str | None,
    parent_version_id: UUID | str | None,
) -> dict:
    """Append a version. Locks the resume row so version numbers never collide."""
    conn.execute(text("SELECT 1 FROM resumes WHERE id = :id FOR UPDATE"), {"id": resume_id})
    row = fetch_one(
        conn,
        "INSERT INTO resume_versions (organization_id, resume_id, version_number,"
        " parent_version_id, source_file_id, content, layout_metadata, extraction_findings)"
        " SELECT roletailor.current_organization_id(), :rid,"
        " coalesce(max(version_number), 0) + 1, :parent, :file, CAST(:content AS jsonb),"
        " CAST(:layout AS jsonb), CAST(:findings AS jsonb)"
        " FROM resume_versions WHERE resume_id = :rid"
        f" RETURNING {VERSION_COLUMNS}",
        {
            "rid": str(resume_id), "parent": str(parent_version_id) if parent_version_id else None,
            "file": str(source_file_id) if source_file_id else None,
            "content": jsonb(content), "layout": jsonb(layout_metadata),
            "findings": jsonb(findings),
        },
    )
    assert row is not None
    return row


def _insert_resume(conn: Connection, principal: Principal, name: str, origin: str, *,
                   processing_file_id: UUID | str | None = None) -> dict:
    """Insert a resume; with `processing_file_id` it starts `processing` (OCR pending)."""
    row = fetch_one(
        conn,
        "INSERT INTO resumes (organization_id, owner_user_id, name, origin, processing_status,"
        " processing_started_at, processing_file_id)"
        " VALUES (:org, :uid, :name, :origin,"
        " CASE WHEN CAST(:file AS uuid) IS NULL THEN NULL ELSE 'processing' END,"
        " CASE WHEN CAST(:file AS uuid) IS NULL THEN NULL ELSE now() END, CAST(:file AS uuid))"
        f" RETURNING {RESUME_COLUMNS}",
        {"org": principal.org_id, "uid": principal.user_id, "name": name, "origin": origin,
         "file": str(processing_file_id) if processing_file_id else None},
    )
    assert row is not None
    return row


def _resume_name(name: str | None, fallback: str) -> str:
    name = (name or "").strip() or fallback
    return name[:200]


# --------------------------------------------------------------------------
# Use cases
# --------------------------------------------------------------------------


def _needs_ocr(doc: ParsedDocument, media_type: str) -> bool:
    """A PDF without a text layer: no blocks, and the parser flagged it as scanned."""
    return (media_type != DOCX_MEDIA_TYPE and not doc.blocks
            and any(f.get("code") == "scanned_pdf_needs_ocr" for f in doc.findings)
            and doc.layout_metadata.get("page_count", 0) > 0)


def create_from_upload(
    principal: Principal, data: bytes, filename: str | None, name: str | None
) -> dict:
    """Store and parse an upload. Text PDFs and DOCX get their first version right away.
    A scanned PDF is stored and the resume is created `processing` without a version; OCR
    runs in the worker (`ocr_resume`), so the result then has `"version": None`."""
    settings = get_settings()
    # Validate and parse first: no transaction is held while parsing, and a file we
    # cannot read is never written to object storage. OCR never runs in the request.
    media_type = files.sniff_upload(data)
    doc = parse_upload(data, media_type)
    queue_ocr = settings.ocr_enabled and _needs_ocr(doc, media_type)
    if queue_ocr:
        pages = doc.layout_metadata["page_count"]
        if pages > settings.ocr_max_pages:
            raise AppError(
                422, "scanned_pdf_too_long",
                f"This PDF is a scan with {pages} pages. We can read scanned resumes of up to "
                f"{settings.ocr_max_pages} pages. Upload a shorter scan, a DOCX, or paste the text.",
            )
    with db.tenant_tx(principal.org_id) as conn:
        stored = files.store(conn, principal.org_id, data, media_type=media_type,
                             filename=filename, category="uploads")
        resume = _insert_resume(
            conn, principal, _resume_name(name, stored["original_filename"]), "upload",
            processing_file_id=stored["id"] if queue_ocr else None,
        )
        version = None
        if not queue_ocr:
            version = insert_version(
                conn, resume["id"], content=document_content(doc),
                layout_metadata=doc.layout_metadata, findings=doc.findings,
                source_file_id=stored["id"], parent_version_id=None,
            )
        audit.record(
            conn, org_id=principal.org_id, action="resume.upload", resource_type="resume",
            resource_id=resume["id"], actor_user_id=principal.user_id,
            metadata={"media_type": stored["media_type"], "byte_size": stored["byte_size"],
                      "sha256": stored["sha256"], **({"ocr": "queued"} if queue_ocr else {})},
        )
    if version is not None:
        return {"resume": resume_out(resume), "version": version_out(version)}
    if not enqueue_ocr(principal.org_id, resume["id"]):
        resume = _get_row(principal, resume["id"])
    return {"resume": resume_out(resume), "version": None}


def enqueue_ocr(org_id: UUID | str, resume_id: UUID | str) -> bool:
    """Hand the OCR job to Celery after the transaction committed. When the broker is down
    the resume is marked failed (`ocr_unavailable`, retryable) instead of failing the request."""
    from roletailor.worker.tasks import ocr_resume

    try:
        ocr_resume.apply_async(args=[str(org_id), str(resume_id)],
                               kwargs={"correlation": correlation_id.get()})
    except Exception:  # kombu raises several unrelated types when the broker is down
        log.exception("ocr enqueue failed", extra={"resume_id": str(resume_id)})
        with db.tenant_tx(org_id) as conn:
            conn.execute(
                text("UPDATE resumes SET processing_status = 'failed',"
                     " processing_error = 'ocr_unavailable'"
                     " WHERE id = :id AND processing_status = 'processing'"),
                {"id": resume_id},
            )
        return False
    return True


def _get_row(principal: Principal, resume_id: UUID | str) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        row = fetch_one(conn, f"SELECT {RESUME_COLUMNS} FROM resumes WHERE id = :id", {"id": resume_id})
    assert row is not None
    return row


def retry_processing(principal: Principal, resume_id: UUID) -> dict:
    """Run OCR again for a scan whose reading failed (or was lost). Returns the resume detail."""
    with db.tenant_tx(principal.org_id) as conn:
        resume = get_owned_resume(conn, principal, resume_id, lock=True)
        state = effective_processing(resume)
        if (resume["archived_at"] is not None or state is None or state[0] != "failed"
                or resume["processing_file_id"] is None):
            raise AppError(409, "not_retryable", "This resume is not waiting for a retry.")
        conn.execute(
            text("UPDATE resumes SET processing_status = 'processing', processing_error = NULL,"
                 " processing_started_at = now() WHERE id = :id"),
            {"id": resume_id},
        )
        audit.record(
            conn, org_id=principal.org_id, action="resume.ocr_retry", resource_type="resume",
            resource_id=resume_id, actor_user_id=principal.user_id,
        )
    enqueue_ocr(principal.org_id, resume_id)
    return get_resume(principal, resume_id)


MIN_TEXT_CHARS = 200
MAX_TEXT_CHARS = 50_000


def create_from_text(principal: Principal, text: str, name: str | None) -> dict:
    """Create a resume from pasted plain text. No source file is stored; the text lives
    in the version's blocks and exports render through the structured template."""
    from roletailor import documents

    if len(text) > MAX_TEXT_CHARS:
        raise AppError(
            413, "resume_text_too_long",
            f"Pasted resumes can be at most {MAX_TEXT_CHARS:,} characters.",
        )
    if len("".join(text.split())) < MIN_TEXT_CHARS:
        raise AppError(
            422, "resume_text_too_short",
            "That looks too short to be a full resume. Paste the complete text of your resume.",
        )
    doc = documents.read_plain_text(text)
    with db.tenant_tx(principal.org_id) as conn:
        resume = _insert_resume(conn, principal, _resume_name(name, "Pasted resume"), "upload")
        version = insert_version(
            conn, resume["id"], content=document_content(doc),
            layout_metadata=doc.layout_metadata, findings=doc.findings,
            source_file_id=None, parent_version_id=None,
        )
        audit.record(
            conn, org_id=principal.org_id, action="resume.paste", resource_type="resume",
            resource_id=resume["id"], actor_user_id=principal.user_id,
            metadata={"char_count": len(text)},
        )
    return {"resume": resume_out(resume), "version": version_out(version)}


def create_guided(principal: Principal, form: guided.GuidedResume) -> dict:
    """Render the form to a DOCX, then parse that DOCX so the version's block ids
    address the stored file exactly like an upload's do."""
    docx_bytes = guided.render(form)
    with db.tenant_tx(principal.org_id) as conn:
        stored = files.store(
            conn, principal.org_id, docx_bytes, media_type=DOCX_MEDIA_TYPE,
            filename=f"{form.name}.docx", category="guided",
        )
        doc = parse_document(docx_bytes, DOCX_MEDIA_TYPE).model_copy(
            update={"source_format": "guided"}
        )
        resume = _insert_resume(conn, principal, _resume_name(form.name, "My resume"), "guided")
        version = insert_version(
            conn, resume["id"], content=document_content(doc),
            layout_metadata=doc.layout_metadata, findings=doc.findings,
            source_file_id=stored["id"], parent_version_id=None,
        )
        audit.record(
            conn, org_id=principal.org_id, action="resume.create_guided", resource_type="resume",
            resource_id=resume["id"], actor_user_id=principal.user_id,
        )
    return {"resume": resume_out(resume), "version": version_out(version)}


def list_resumes(principal: Principal) -> list[dict]:
    with db.tenant_tx(principal.org_id) as conn:
        rows = fetch_all(
            conn,
            "SELECT r.id, r.name, r.origin, r.created_at, r.processing_status, r.processing_error,"
            " r.processing_started_at, v.id AS v_id,"
            " v.version_number AS v_number, v.created_at AS v_created_at"
            " FROM resumes r"
            " LEFT JOIN LATERAL (SELECT id, version_number, created_at FROM resume_versions"
            "   WHERE resume_id = r.id ORDER BY version_number DESC LIMIT 1) v ON true"
            " WHERE r.owner_user_id = :uid AND r.archived_at IS NULL"
            " ORDER BY r.created_at DESC",
            {"uid": principal.user_id},
        )
    return [
        {
            "id": r["id"], "name": r["name"], "origin": r["origin"], "created_at": r["created_at"],
            "processing": processing_out(r),
            "latest_version": {
                "id": r["v_id"], "version_number": r["v_number"], "created_at": r["v_created_at"],
            } if r["v_id"] else None,
        }
        for r in rows
    ]


def get_resume(principal: Principal, resume_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        resume = get_owned_resume(conn, principal, resume_id)
        versions = fetch_all(
            conn,
            "SELECT id, version_number, parent_version_id, source_file_id, created_at"
            " FROM resume_versions WHERE resume_id = :id ORDER BY version_number",
            {"id": resume_id},
        )
    return {**resume_out(resume), "versions": versions}


def rename(principal: Principal, resume_id: UUID, name: str) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        get_owned_resume(conn, principal, resume_id)
        row = fetch_one(
            conn,
            f"UPDATE resumes SET name = :name WHERE id = :id RETURNING {RESUME_COLUMNS}",
            {"name": _resume_name(name, "My resume"), "id": resume_id},
        )
    assert row is not None
    return resume_out(row)


def archive(principal: Principal, resume_id: UUID) -> None:
    with db.tenant_tx(principal.org_id) as conn:
        get_owned_resume(conn, principal, resume_id)
        conn.execute(
            text("UPDATE resumes SET archived_at = coalesce(archived_at, now()) WHERE id = :id"),
            {"id": resume_id},
        )
        audit.record(
            conn, org_id=principal.org_id, action="resume.archive", resource_type="resume",
            resource_id=resume_id, actor_user_id=principal.user_id,
        )


def _version_of_resume(conn: Connection, resume_id: UUID, version_id: UUID) -> dict:
    row = get_version(conn, version_id)
    if row["resume_id"] != resume_id:
        raise not_found("Resume version")
    return row


def get_resume_version(principal: Principal, resume_id: UUID, version_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        get_owned_resume(conn, principal, resume_id)
        return version_out(_version_of_resume(conn, resume_id, version_id))


def restore_version(principal: Principal, resume_id: UUID, version_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        get_owned_resume(conn, principal, resume_id)
        source = _version_of_resume(conn, resume_id, version_id)
        row = insert_version(
            conn, resume_id, content=source["content"],
            layout_metadata=source["layout_metadata"], findings=source["extraction_findings"],
            source_file_id=source["source_file_id"], parent_version_id=source["id"],
        )
    return version_out(row)

