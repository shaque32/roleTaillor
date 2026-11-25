from __future__ import annotations

import hmac
import logging

import redis
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import Connection, text

from roletailor import db
from roletailor.config import get_settings
from roletailor.services.errors import not_found

log = logging.getLogger(__name__)
router = APIRouter(tags=["ops"])


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        with db.global_tx() as conn:
            conn.execute(text("SELECT 1"))
            checks["tenant_isolation"] = _tenant_isolation(conn)
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
    try:
        redis.Redis.from_url(get_settings().redis_url, socket_timeout=1, socket_connect_timeout=1).ping()
        checks["redis"] = "ok"
    except redis.RedisError as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ready" if ready else "not_ready", "checks": checks},
                        status_code=200 if ready else 503)


_ROLE_SQL = text(
    "SELECT r.rolsuper OR r.rolbypassrls AS bypasses,"
    " EXISTS (SELECT 1 FROM pg_tables t WHERE t.schemaname = 'roletailor'"
    "         AND t.tableowner = current_user) AS owns_tables"
    " FROM pg_roles r WHERE r.rolname = current_user"
)
_isolation_ok = False


def _tenant_isolation(conn: Connection) -> str:
    """Row-level security only binds a role that is neither a superuser, BYPASSRLS, nor
    the table owner. If RT_DATABASE_URL points at such a role every tenant can read every
    other tenant's rows, so the instance must not take traffic."""
    global _isolation_ok
    if _isolation_ok:
        return "ok"
    row = conn.execute(_ROLE_SQL).mappings().first()
    if row is None or row["bypasses"] or row["owns_tables"]:
        log.critical("database role bypasses row-level security; refusing readiness")
        return "error: database role bypasses row-level security"
    _isolation_ok = True
    return "ok"


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    settings = get_settings()
    token = settings.metrics_token
    authorized = bool(token) and hmac.compare_digest(
        request.headers.get("authorization", "").encode(), f"Bearer {token}".encode())
    if not authorized:
        # A scraper on the private network reaches the process directly; anything that
        # carries the edge's client-address header came from the internet.
        from_edge = bool(settings.client_ip_header) and settings.client_ip_header in request.headers
        if token or from_edge:
            raise not_found("Page")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
