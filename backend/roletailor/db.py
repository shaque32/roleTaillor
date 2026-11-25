"""Database access: a sync SQLAlchemy Core engine on the RLS-bound app role.

All tenant data is read and written inside `tenant_tx(org_id)`, which pins the
transaction to one organization through the `app.organization_id` setting that
the RLS policies in db/migrations/001 check. Global tables (users, sessions,
consents, catalogs, webhook events) use `global_tx()`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

from roletailor.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_settings().database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=10,
            connect_args={"options": "-c search_path=roletailor,public"},
        )
    return _engine


def reset_engine() -> None:
    """Dispose the pooled engine so the next call picks up current settings."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def set_tenant(conn: Connection, org_id: UUID | str) -> None:
    """Scope the current transaction to one organization (transaction-local)."""
    conn.execute(
        text("SELECT set_config('app.organization_id', :org, true)"), {"org": str(org_id)}
    )


@contextmanager
def tenant_tx(org_id: UUID | str) -> Iterator[Connection]:
    with get_engine().begin() as conn:
        set_tenant(conn, org_id)
        yield conn


@contextmanager
def global_tx() -> Iterator[Connection]:
    with get_engine().begin() as conn:
        yield conn
