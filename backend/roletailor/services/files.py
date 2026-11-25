"""stored_files rows: write-through storage, scanning, and guarded reads."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from roletailor.config import get_settings
from roletailor.services.errors import AppError, not_found
from roletailor.services.sql import fetch_one
from roletailor.storage import (
    EXTENSIONS,
    UnsupportedFile,
    get_scanner,
    get_storage,
    sha256_hex,
    sniff_media_type,
)

FILE_COLUMNS = (
    "id, bucket, object_key, object_version, original_filename, media_type, byte_size,"
    " sha256, scan_status, created_at"
)
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_filename(name: str | None, media_type: str) -> str:
    stem = _UNSAFE_FILENAME.sub("", (name or "").rsplit("/", 1)[-1]).strip(" .")[:120]
    extension = EXTENSIONS.get(media_type, "")
    if not stem:
        stem = "resume"
    return stem if stem.lower().endswith(extension) else stem + extension


def store(
    conn: Connection,
    org_id: UUID | str,
    data: bytes,
    *,
    media_type: str,
    filename: str | None,
    category: str,
) -> dict:
    """Write bytes to object storage, record them as `pending`, then scan.
    Raises 422 file_blocked when the scanner rejects the content."""
    storage = get_storage()
    extension = EXTENSIONS.get(media_type, ".bin")
    key = f"{org_id}/{category}/{uuid4().hex}{extension}"
    version = storage.put(key, data, media_type)
    row = fetch_one(
        conn,
        "INSERT INTO stored_files (organization_id, bucket, object_key, object_version,"
        " original_filename, media_type, byte_size, sha256, scan_status)"
        " VALUES (:org, :bucket, :key, :version, :name, :media, :size, :sha, 'pending')"
        f" RETURNING {FILE_COLUMNS}",
        {
            "org": str(org_id), "bucket": storage.bucket, "key": key, "version": version,
            "name": safe_filename(filename, media_type), "media": media_type,
            "size": len(data), "sha": sha256_hex(data),
        },
    )
    assert row is not None
    status = get_scanner().scan(data, media_type)
    conn.execute(
        text("UPDATE stored_files SET scan_status = :s WHERE id = :id"),
        {"s": status, "id": row["id"]},
    )
    row["scan_status"] = status
    if status != "clean":
        storage.delete(key, version)  # the row rolls back with the request; drop the bytes too
        raise AppError(422, "file_blocked", "This file failed the security scan.")
    return row


def store_upload(conn: Connection, org_id: UUID | str, data: bytes, filename: str | None) -> dict:
    """Validate an untrusted upload (DOCX/PDF only, size-capped) and store it."""
    try:
        media_type = sniff_media_type(data, get_settings().max_upload_bytes)
    except UnsupportedFile as exc:
        status = 413 if exc.code == "file_too_large" else 415
        raise AppError(status, exc.code, str(exc)) from exc
    return store(conn, org_id, data, media_type=media_type, filename=filename, category="uploads")


def get_clean(conn: Connection, file_id: UUID | str) -> dict:
    row = fetch_one(conn, f"SELECT {FILE_COLUMNS} FROM stored_files WHERE id = :id", {"id": file_id})
    if row is None:
        raise not_found("File")
    if row["scan_status"] != "clean":
        raise AppError(409, "file_unavailable", "This file is not available for download.")
    return row


def read_bytes(conn: Connection, file_id: UUID | str) -> tuple[dict, bytes]:
    row = get_clean(conn, file_id)
    return row, get_storage().get(row["object_key"], row["object_version"])


def signed_url(row: dict) -> tuple[str, datetime]:
    """A short-lived download URL for a clean file row."""
    if row["scan_status"] != "clean":
        raise AppError(409, "file_unavailable", "This file is not available for download.")
    ttl = get_settings().signed_url_ttl_seconds
    url = get_storage().signed_url(
        row["object_key"], row["object_version"],
        filename=row["original_filename"] or "download", media_type=row["media_type"], ttl=ttl,
    )
    return url, datetime.now(UTC) + timedelta(seconds=ttl)
