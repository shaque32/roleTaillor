"""roletailor_ops views: shape, value domains and privilege boundaries."""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from tests.platform.conftest import create_job, upload_resume
from tests.platform.test_workflows import start

STAGES = {"structure_resume", "analyze_job", "plan", "rewrite", "verify_claims", "feedback", "other"}
ROUTES = {"primary", "failover", "escalated", "cache"}
FABRICATION = {"facts.numbers", "facts.terms", "facts.keywords", "facts.claims"}


_ROLE_URLS = {
    "rt_app": ("RT_TEST_APP_DATABASE_URL", "postgresql://rt_app:rt_app@localhost:5432/postgres"),
    "rt_metrics": ("RT_TEST_METRICS_DATABASE_URL", "postgresql://rt_metrics:rt_metrics@localhost:5432/postgres"),
}


def _url(user: str, database: str) -> str:
    """The role's configured URL (credentials, host and options kept) on the test database."""
    env, default = _ROLE_URLS[user]
    parts = urlsplit(os.environ.get(env, default).replace("postgresql+psycopg://", "postgresql://", 1))
    return urlunsplit(parts._replace(path=f"/{database}"))


@pytest.fixture()
def metrics(database):
    try:
        conn = psycopg.connect(_url("rt_metrics", database), autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"rt_metrics role is not available: {exc}")
    with conn:
        yield conn


@pytest.fixture()
def generated(make_user, classic_docx):
    user = make_user()
    version = upload_resume(user, classic_docx)["version"]
    r = start(user, version["id"], create_job(user)["id"])
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "completed"
    return user, r.json()["id"]


def test_views_return_sane_rows(metrics, generated):
    user, wid = generated
    q = metrics.execute

    calls = q("SELECT stage, route, calls, cost_usd, p95_latency_ms, status "
              "FROM roletailor_ops.ai_calls_hourly").fetchall()
    assert calls
    for stage, route, n, cost, _p95, _status in calls:
        assert stage in STAGES and route in ROUTES
        assert n > 0 and cost >= 0

    gen = q("SELECT organization_id, status, iterations, ai_calls, cost_usd, planned_blocks, "
            "fabrication_flagged_blocks, reverted_blocks, wall_seconds, started_at <= finished_at "
            "FROM roletailor_ops.generations WHERE workflow_id = %s", (wid,)).fetchone()
    assert gen is not None
    org, status, iters, ai_calls, cost, planned, flagged, reverted, wall, ordered = gen
    assert str(org) == user.org_id and status == "completed" and ordered
    assert iters >= 1 and ai_calls > 0 and cost >= 0 and wall >= 0
    assert planned > 0
    assert 0 <= flagged <= planned * len(FABRICATION) and reverted >= 0

    daily = q("SELECT generations, cost_usd, avg_cost_usd, p50_cost_usd, p95_cost_usd, "
              "fabrication_attempt_rate FROM roletailor_ops.generations_daily").fetchall()
    assert daily and all(d[0] > 0 and d[1] >= 0 and d[2] >= 0 for d in daily)
    assert all(d[5] is None or d[5] >= 0 for d in daily)

    rules = q("SELECT rule_key, planned_blocks, flagged_blocks, reverted_blocks, flagged_rate "
              "FROM roletailor_ops.validation_daily").fetchall()
    assert {r[0] for r in rules} >= FABRICATION
    assert all(r[1] > 0 and r[2] >= 0 and r[3] >= 0 for r in rules)
    assert all(r[4] is None or 0 <= r[4] <= 1 for r in rules)

    orgs = q("SELECT organization_id, generations, cost_usd FROM roletailor_ops.cost_by_org_daily").fetchall()
    assert user.org_id in {str(o[0]) for o in orgs} and all(o[1] > 0 and o[2] >= 0 for o in orgs)

    rel = q("SELECT stage, calls, failure_rate, fallback_rate, avg_cost_usd "
            "FROM roletailor_ops.release_quality_daily").fetchall()
    assert rel
    for stage, n, fail, fallback, avg in rel:
        assert stage in STAGES and n > 0 and 0 <= fail <= 1 and 0 <= fallback <= 1 and avg >= 0


def test_privilege_boundaries(metrics, database, generated):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        metrics.execute("SELECT 1 FROM roletailor.ai_metrics LIMIT 1")
    writable = metrics.execute(
        "SELECT bool_or(has_table_privilege(c.oid, p)) FROM pg_class c"
        " CROSS JOIN unnest(ARRAY['INSERT', 'UPDATE', 'DELETE']) p"
        " WHERE c.relnamespace = 'roletailor_ops'::regnamespace AND c.relkind = 'v'").fetchone()[0]
    assert writable is False
    with psycopg.connect(_url("rt_app", database), autocommit=True) as app, \
            pytest.raises(psycopg.errors.InsufficientPrivilege):
        app.execute("SELECT 1 FROM roletailor_ops.generations LIMIT 1")
