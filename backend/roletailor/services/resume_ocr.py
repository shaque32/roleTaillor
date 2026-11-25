"""Read a scanned resume with OCR in the worker and give it its first version.

Three steps, none holding a transaction while OCR runs: claim (lock the row, check it is
still waiting, read the stored file), parse in the sandbox with OCR on, then persist the
version or the failure. Deterministic failures are stored on the resume (`processing_error`)
and returned as outcomes; infrastructure errors propagate so the task can retry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from roletailor import db
from roletailor.config import get_settings
from roletailor.documents import sandbox
from roletailor.documents.model import ParsedDocument
from roletailor.services import audit, files, resumes
from roletailor.services.sql import fetch_one

log = logging.getLogger(__name__)

READY, NO_TEXT, TIMEOUT, FAILED, SKIPPED = "ready", "no_text", "timeout", "failed", "skipped"
_CODES = {NO_TEXT: "ocr_no_text", TIMEOUT: "ocr_timeout", FAILED: "ocr_failed"}


def is_transient(exc: BaseException) -> bool:
    """Busy parser, storage and database blips are worth a Celery retry."""
    if isinstance(exc, sandbox.ParserBusy | OSError | OperationalError | InterfaceError):
        return True
    if isinstance(exc, DBAPIError):
        return bool(exc.connection_invalidated)
    try:
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:  # boto3 is only installed with the s3 storage extra
        return False
    return isinstance(exc, BotoCoreError | ClientError)


@dataclass(frozen=True)
class _Claim:
    data: bytes
    started_at: datetime | None


def _claim(org_id: str, resume_id: str) -> _Claim | None:
    with db.tenant_tx(org_id) as conn:
        row = fetch_one(
            conn,
            "SELECT processing_status, processing_file_id, processing_started_at, archived_at,"
            " EXISTS (SELECT 1 FROM resume_versions v WHERE v.resume_id = resumes.id) AS has_version"
            " FROM resumes WHERE id = :id FOR UPDATE",
            {"id": resume_id},
        )
        if (row is None or row["processing_status"] != "processing" or row["archived_at"] is not None
                or row["has_version"] or row["processing_file_id"] is None):
            return None  # archived, finished, failed, or a duplicate delivery
        _, data = files.read_bytes(conn, row["processing_file_id"])
        return _Claim(data, row["processing_started_at"])


def _parse(data: bytes) -> ParsedDocument:
    settings = get_settings()
    return sandbox.parse_untrusted(
        data, "pdf", timeout=settings.ocr_timeout_seconds, memory_mb=settings.ocr_memory_limit_mb,
        cpu_seconds=settings.ocr_cpu_seconds, max_pages=settings.max_resume_pdf_pages,
        max_blocks=settings.max_resume_blocks, ocr=True, ocr_max_pages=settings.ocr_max_pages,
        ocr_deadline=settings.ocr_deadline_seconds,
    )


def _failure_outcome(doc: ParsedDocument) -> str:
    """Why a document without blocks came back: what the sandbox child recorded."""
    return {"no_text": NO_TEXT, "timeout": TIMEOUT}.get(doc.layout_metadata.get("ocr_outcome"), FAILED)


def _complete(conn: Connection, org_id: str, resume_id: str, doc: ParsedDocument) -> bool:
    row = fetch_one(
        conn,
        "SELECT owner_user_id, processing_status, processing_file_id, archived_at,"
        " EXISTS (SELECT 1 FROM resume_versions v WHERE v.resume_id = resumes.id) AS has_version"
        " FROM resumes WHERE id = :id FOR UPDATE",
        {"id": resume_id},
    )
    if (row is None or row["processing_status"] != "processing" or row["archived_at"] is not None
            or row["has_version"]):
        return False
    resumes.insert_version(
        conn, resume_id, content=resumes.document_content(doc),
        layout_metadata=doc.layout_metadata, findings=doc.findings,
        source_file_id=row["processing_file_id"], parent_version_id=None,
    )
    conn.execute(
        text("UPDATE resumes SET processing_status = NULL, processing_error = NULL,"
             " processing_started_at = NULL, processing_file_id = NULL WHERE id = :id"),
        {"id": resume_id},
    )
    audit.record(
        conn, org_id=org_id, action="resume.ocr_completed", resource_type="resume",
        resource_id=resume_id, actor_user_id=row["owner_user_id"],
        metadata={"pages": doc.layout_metadata.get("page_count"), "blocks": len(doc.blocks),
                  "mean_confidence": doc.layout_metadata.get("ocr_mean_confidence")},
    )
    return True


def mark_failed(org_id: str, resume_id: str, outcome: str, started_at: datetime | None = None) -> bool:
    """Record a failed read. With `started_at`, only the attempt that claimed the row may fail it,
    so a slow earlier attempt cannot fail a retry the user has started since."""
    code = _CODES[outcome]
    with db.tenant_tx(org_id) as conn:
        row = fetch_one(
            conn,
            "UPDATE resumes SET processing_status = 'failed', processing_error = :code"
            " WHERE id = :id AND processing_status = 'processing'"
            " AND (CAST(:started AS timestamptz) IS NULL OR processing_started_at = :started)"
            " RETURNING owner_user_id",
            {"id": resume_id, "code": code, "started": started_at},
        )
        if row is None:
            return False
        audit.record(
            conn, org_id=org_id, action="resume.ocr_failed", resource_type="resume",
            resource_id=resume_id, actor_user_id=row["owner_user_id"], metadata={"code": code},
        )
    return True


def run(org_id: str, resume_id: str) -> str:
    """Read one resume. Returns ready, no_text, timeout, failed or skipped. Infrastructure
    errors (storage, database, a busy parser) propagate for the task to retry."""
    UUID(resume_id)  # a malformed id is a caller bug, not a transient fault
    claim = _claim(org_id, resume_id)
    if claim is None:
        return SKIPPED
    try:
        doc = _parse(claim.data)
    except sandbox.ParseTimeout:
        outcome = TIMEOUT
    except sandbox.InvalidDocument:  # DocumentRejected, ParseFailed or a bad PDF
        outcome = FAILED
    else:
        if doc.blocks:
            with db.tenant_tx(org_id) as conn:
                if _complete(conn, org_id, resume_id, doc):
                    return READY
            return SKIPPED  # archived or finished while OCR ran
        outcome = _failure_outcome(doc)
    mark_failed(org_id, resume_id, outcome, claim.started_at)
    return outcome
