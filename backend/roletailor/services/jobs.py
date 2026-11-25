"""Job postings: pasted descriptions or fetched URLs."""

from __future__ import annotations

from uuid import UUID

from roletailor import db
from roletailor.config import get_settings
from roletailor.services import job_fetch
from roletailor.services.auth import Principal
from roletailor.services.errors import AppError, not_found
from roletailor.services.sql import fetch_one

JOB_COLUMNS = "id, source_url, title, company, description, created_at"
MAX_DESCRIPTION_CHARS = 50_000


def _trim(value: str | None, limit: int) -> str | None:
    value = (value or "").strip()
    return value[:limit] or None


def create_job(
    principal: Principal,
    *,
    source_url: str | None,
    description: str | None,
    title: str | None,
    company: str | None,
) -> dict:
    description = _trim(description, MAX_DESCRIPTION_CHARS)
    if description is None:
        if not source_url:
            raise AppError(422, "job_input_required", "Paste a job description or give a URL.")
        settings = get_settings()
        try:
            fetched = job_fetch.fetch_job_page(
                source_url, timeout=settings.job_fetch_timeout_seconds,
                max_bytes=settings.job_fetch_max_bytes,
                board_max_bytes=settings.job_fetch_board_max_bytes,
            )
        except job_fetch.JobFetchError as exc:
            raise AppError(
                422, "job_url_unreadable",
                "We could not read that job page. Paste the job description instead.",
                {"reason": str(exc)},
            ) from exc
        description = fetched.text[:MAX_DESCRIPTION_CHARS]
        title = title or fetched.title
        company = company or fetched.company
    with db.tenant_tx(principal.org_id) as conn:
        row = fetch_one(
            conn,
            "INSERT INTO job_postings (organization_id, source_url, title, company, description)"
            f" VALUES (:org, :url, :title, :company, :desc) RETURNING {JOB_COLUMNS}",
            {
                "org": principal.org_id, "url": _trim(source_url, 2000),
                "title": _trim(title, 300), "company": _trim(company, 300), "desc": description,
            },
        )
    assert row is not None
    return row


def get_job(principal: Principal, job_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        row = fetch_one(conn, f"SELECT {JOB_COLUMNS} FROM job_postings WHERE id = :id", {"id": job_id})
    if row is None:
        raise not_found("Job posting")
    return row
