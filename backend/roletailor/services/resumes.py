"""Resumes and their immutable versions (uploads, guided creation, restores)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from roletailor import db
from roletailor.documents.model import ParsedDocument
from roletailor.services import audit, files, guided
from roletailor.services.auth import Principal
from roletailor.services.errors import AppError, not_found
from roletailor.services.sql import fetch_all, fetch_one, jsonb
from roletailor.storage import DOCX_MEDIA_TYPE

RESUME_COLUMNS = "id, name, origin, created_at, archived_at"
_VERSION_FIELDS = (
    "id", "resume_id", "version_number", "parent_version_id", "source_file_id", "content",
    "layout_metadata", "extraction_findings", "created_at",
)
VERSION_COLUMNS = ", ".join(_VERSION_FIELDS)


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
        " AND purged_at IS NULL" + (" FOR UPDATE" if lock else ""),
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


def get_owned_version(conn: Connection, principal: Principal, version_id: UUID, *,
                      hold=False) -> dict:
    """`hold` share-locks the resume until commit, so the retention purge cannot erase
    it between this check and the caller's write."""
    row = fetch_one(
        conn,
        f"SELECT {', '.join('v.' + f for f in _VERSION_FIELDS)} FROM resume_versions v"
        " JOIN resumes r ON r.id = v.resume_id"
        " WHERE v.id = :id AND r.owner_user_id = :uid AND r.purged_at IS NULL"
        + (" FOR SHARE OF r" if hold else ""),
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


def _insert_resume(conn: Connection, principal: Principal, name: str, origin: str) -> dict:
    row = fetch_one(
        conn,
        "INSERT INTO resumes (organization_id, owner_user_id, name, origin)"
        f" VALUES (:org, :uid, :name, :origin) RETURNING {RESUME_COLUMNS}",
        {"org": principal.org_id, "uid": principal.user_id, "name": name, "origin": origin},
    )
    assert row is not None
    return row


def _resume_name(name: str | None, fallback: str) -> str:
    name = (name or "").strip() or fallback
    return name[:200]


# --------------------------------------------------------------------------
# Use cases
# --------------------------------------------------------------------------


def create_from_upload(
    principal: Principal, data: bytes, filename: str | None, name: str | None
) -> dict:
    # Validate and parse first: no transaction is held while parsing, and a file we
    # cannot read is never written to object storage.
    media_type = files.sniff_upload(data)
    doc = parse_upload(data, media_type)
    with db.tenant_tx(principal.org_id) as conn:
        stored = files.store(conn, principal.org_id, data, media_type=media_type,
                             filename=filename, category="uploads")
        resume = _insert_resume(
            conn, principal, _resume_name(name, stored["original_filename"]), "upload"
        )
        version = insert_version(
            conn, resume["id"], content=document_content(doc),
            layout_metadata=doc.layout_metadata, findings=doc.findings,
            source_file_id=stored["id"], parent_version_id=None,
        )
        audit.record(
            conn, org_id=principal.org_id, action="resume.upload", resource_type="resume",
            resource_id=resume["id"], actor_user_id=principal.user_id,
            metadata={"media_type": stored["media_type"], "byte_size": stored["byte_size"],
                      "sha256": stored["sha256"]},
        )
    return {"resume": resume, "version": version_out(version)}


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
    return {"resume": resume, "version": version_out(version)}


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
    return {"resume": resume, "version": version_out(version)}


def list_resumes(principal: Principal) -> list[dict]:
    with db.tenant_tx(principal.org_id) as conn:
        rows = fetch_all(
            conn,
            "SELECT r.id, r.name, r.origin, r.created_at, v.id AS v_id,"
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
    return {**resume, "versions": versions}


def rename(principal: Principal, resume_id: UUID, name: str) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        get_owned_resume(conn, principal, resume_id)
        row = fetch_one(
            conn,
            f"UPDATE resumes SET name = :name WHERE id = :id RETURNING {RESUME_COLUMNS}",
            {"name": _resume_name(name, "My resume"), "id": resume_id},
        )
    assert row is not None
    return row


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

