"""Small helpers shared by the repository modules."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Connection, text


def jsonb(value: Any) -> str:
    """Serialize a value for a `CAST(:param AS jsonb)` bind."""
    return json.dumps(value, default=str)


def fetch_one(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> dict | None:
    row = conn.execute(text(sql), params or {}).mappings().first()
    return dict(row) if row else None


def fetch_all(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
    return [dict(r) for r in conn.execute(text(sql), params or {}).mappings()]
