"""Apply db/migrations/*.sql in filename order, once each.

Runs as the schema owner (RT_MIGRATION_DATABASE_URL). Applied versions are tracked in
public.schema_migrations; an advisory lock keeps concurrent runners from racing.
Each migration file manages its own transaction (BEGIN ... COMMIT).

    python db/migrate.py                 # apply pending migrations
    python db/migrate.py --baseline 001  # record 001 as applied without running it
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_LOCK_KEY = 7_300_421_001  # arbitrary, constant per application
_DEFAULT_URL = "postgresql://rt_owner:rt_owner@localhost:5432/roletailor"


def _libpq_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _version(path: Path) -> str:
    return path.name.split("_", 1)[0]


def _migration_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.sql"), key=lambda p: p.name)


def _ensure_table(conn: psycopg.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS public.schema_migrations ("
        " version text PRIMARY KEY, filename text NOT NULL,"
        " applied_at timestamptz NOT NULL DEFAULT now())"
    )


def _applied(conn: psycopg.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT version FROM public.schema_migrations")}


def _record(conn: psycopg.Connection, path: Path) -> None:
    conn.execute(
        "INSERT INTO public.schema_migrations (version, filename) VALUES (%s, %s)",
        (_version(path), path.name),
    )


def apply_migrations(url: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations and return the filenames applied."""
    applied_now: list[str] = []
    with psycopg.connect(_libpq_url(url), autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_KEY,))
        try:
            _ensure_table(conn)
            done = _applied(conn)
            for path in _migration_files(directory):
                if _version(path) in done:
                    continue
                conn.execute(path.read_text(encoding="utf-8"))
                _record(conn, path)
                applied_now.append(path.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
    return applied_now


def baseline(url: str, up_to: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Mark migrations up to and including `up_to` as applied (for databases that
    were initialised by hand before the runner existed)."""
    marked: list[str] = []
    with psycopg.connect(_libpq_url(url), autocommit=True) as conn:
        _ensure_table(conn)
        done = _applied(conn)
        for path in _migration_files(directory):
            if _version(path) > up_to:
                break
            if _version(path) not in done:
                _record(conn, path)
                marked.append(path.name)
    return marked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", metavar="VERSION")
    args = parser.parse_args(argv)
    url = os.environ.get("RT_MIGRATION_DATABASE_URL", _DEFAULT_URL)
    if args.baseline:
        names = baseline(url, args.baseline)
        print(f"baselined: {', '.join(names) or 'nothing'}")
    else:
        names = apply_migrations(url)
        print(f"applied: {', '.join(names) or 'nothing (up to date)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
