"""roletailor_ops views: shape, value domains and privilege boundaries."""

from __future__ import annotations

import json
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


# --- fabrication counts, historical rows and call timestamps ---------------------------------

def _owner_url(database: str) -> str:
    from roletailor.config import get_settings

    owner = os.environ.get("RT_MIGRATION_DATABASE_URL", get_settings().migration_database_url)
    parts = urlsplit(owner.replace("postgresql+psycopg://", "postgresql://", 1))
    return urlunsplit(parts._replace(path=f"/{database}"))


@pytest.fixture()
def owner(database):
    """Schema owner connection, used to arrange rows the app role could not write directly."""
    with psycopg.connect(_owner_url(database), autocommit=True) as conn:
        yield conn


def _workflow_on(owner, make_user, classic_docx, day: str) -> tuple[str, str]:
    """A completed generation whose AI calls are moved to `day`, so `generations_daily` for
    that day only holds the workflows a test arranged. Its validation rows are removed."""
    user = make_user()
    version = upload_resume(user, classic_docx)["version"]
    r = start(user, version["id"], create_job(user)["id"])
    assert r.status_code == 202 and r.json()["status"] == "completed", r.text
    wid = r.json()["id"]
    owner.execute("UPDATE roletailor.ai_metrics SET created_at = %s::timestamptz WHERE workflow_id = %s",
                  (f"{day} 12:00+00", wid))
    owner.execute("DELETE FROM roletailor.validation_results WHERE workflow_id = %s", (wid,))
    return user.org_id, wid


def _iteration(owner, org: str, wid: str, at: str, planned: int, flagged: int | None) -> None:
    """One iteration's validation rows: pipeline.coverage always, pipeline.fabrication only
    when `flagged` is given (iterations recorded before that row existed have none)."""
    rows = [("pipeline.coverage", None, {"planned_blocks": planned, "reverted_blocks": 0})]
    if flagged is not None:
        rows.append(("pipeline.fabrication", round(100.0 * (1 - flagged / planned), 2),
                     {"flagged_blocks": flagged, "planned_blocks": planned, "reverted_blocks": 0}))
    for rule, score, details in rows:
        owner.execute(
            "INSERT INTO roletailor.validation_results (organization_id, workflow_id, rule_key,"
            " rule_version, passed, score, details, created_at)"
            " VALUES (%s, %s, %s, 'test', true, %s, %s::jsonb, %s::timestamptz)",
            (org, wid, rule, score, json.dumps(details), at))


def _generation(metrics, wid: str):
    return metrics.execute(
        "SELECT planned_blocks, fabrication_flagged_blocks, fabrication_planned_blocks,"
        " fabrication_attempt_rate FROM roletailor_ops.generations WHERE workflow_id = %s",
        (wid,)).fetchone()


def _daily_rate(metrics, day: str):
    row = metrics.execute(
        "SELECT generations, fabrication_attempt_rate FROM roletailor_ops.generations_daily"
        " WHERE day = %s::date AND status = 'completed'", (day,)).fetchone()
    assert row is not None
    return row


def test_block_tripping_two_fabrication_rules_counts_once(metrics, owner, make_user, classic_docx):
    org, wid = _workflow_on(owner, make_user, classic_docx, "2001-01-01")
    at = "2001-01-01 12:05+00"
    # Block b1 trips facts.numbers and facts.terms; 10 blocks planned, so each per-rule row
    # reads 90 and the distinct count on pipeline.fabrication is 1, not 2.
    for rule in ("facts.numbers", "facts.terms"):
        owner.execute(
            "INSERT INTO roletailor.validation_results (organization_id, workflow_id, rule_key,"
            " rule_version, passed, score, details, created_at)"
            " VALUES (%s, %s, %s, 'test', true, 90, '{}'::jsonb, %s::timestamptz)", (org, wid, rule, at))
    _iteration(owner, org, wid, at, planned=10, flagged=1)

    assert _generation(metrics, wid) == (10, 1, 10, pytest.approx(0.1))
    assert _daily_rate(metrics, "2001-01-01") == (1, pytest.approx(0.1))
    per_rule = dict(metrics.execute(
        "SELECT rule_key, sum(flagged_blocks) FROM roletailor_ops.validation_daily"
        " WHERE day = '2001-01-01' GROUP BY rule_key").fetchall())
    assert per_rule["facts.numbers"] == per_rule["facts.terms"] == 1  # breakdown overlaps, rate does not


def test_historical_iterations_without_fabrication_rows_are_unknown(metrics, owner, make_user, classic_docx):
    org, wid = _workflow_on(owner, make_user, classic_docx, "2001-01-02")
    _iteration(owner, org, wid, "2001-01-02 12:05+00", planned=10, flagged=None)
    _iteration(owner, org, wid, "2001-01-02 12:10+00", planned=10, flagged=None)

    # Counts are unknown (NULL), not zero, and the rate is NULL rather than 0.
    assert _generation(metrics, wid) == (20, None, None, None)
    assert _daily_rate(metrics, "2001-01-02") == (1, None)


def test_mixed_old_and_new_iterations_use_only_known_blocks(metrics, owner, make_user, classic_docx):
    org, wid = _workflow_on(owner, make_user, classic_docx, "2001-01-03")
    _iteration(owner, org, wid, "2001-01-03 12:05+00", planned=10, flagged=None)  # old iteration
    _iteration(owner, org, wid, "2001-01-03 12:10+00", planned=10, flagged=3)     # new iteration

    # 3 / 10 over the iteration that has a count, not 3 / 20.
    assert _generation(metrics, wid) == (20, 3, 10, pytest.approx(0.3))
    assert _daily_rate(metrics, "2001-01-03") == (1, pytest.approx(0.3))


def test_daily_rate_skips_historical_workflows(metrics, owner, make_user, classic_docx):
    day = "2001-01-04"
    old_org, old = _workflow_on(owner, make_user, classic_docx, day)
    new_org, new = _workflow_on(owner, make_user, classic_docx, day)
    _iteration(owner, old_org, old, f"{day} 12:05+00", planned=10, flagged=None)
    _iteration(owner, new_org, new, f"{day} 12:05+00", planned=10, flagged=2)

    generations, rate = _daily_rate(metrics, day)
    assert generations == 2
    assert rate == pytest.approx(0.2)  # not 2 / 20


def test_wall_seconds_uses_call_completion_times(metrics, owner, make_user, classic_docx):
    """A call persisted late keeps its real completion time (created_at), so the span is
    first start to last completion, not first start to last persistence."""
    from datetime import UTC, datetime, timedelta

    from roletailor.ai.telemetry import CallRecord
    from roletailor.services.metrics_sink import DbMetricsSink

    user = make_user()
    version = upload_resume(user, classic_docx)["version"]
    r = start(user, version["id"], create_job(user)["id"])
    assert r.status_code == 202, r.text
    wid = r.json()["id"]
    owner.execute("DELETE FROM roletailor.validation_results WHERE workflow_id = %s", (wid,))
    owner.execute("DELETE FROM roletailor.ai_metrics WHERE workflow_id = %s", (wid,))

    t0 = datetime(2001, 1, 5, 12, 0, tzinfo=UTC)
    sink = DbMetricsSink(user.org_id, wid)

    def record(stage: str, completed: datetime, latency_ms: int) -> None:
        sink.record(CallRecord(
            stage=stage, attempt=1, provider="prov", model_name="mod", model_revision="r",
            capability_tier="low", prompt_key="plan", prompt_version=1, prompt_text="t",
            status="succeeded", routing_reason="primary", latency_ms=latency_ms,
            completed_at=completed))

    # Call 1 runs 0-30s and call 2 completes at 50s; both are persisted just now, long after.
    record("it1:plan", t0 + timedelta(seconds=30), 30_000)
    record("it1:rewrite:b1", t0 + timedelta(seconds=50), 20_000)

    stored = [row[0] for row in owner.execute(
        "SELECT created_at FROM roletailor.ai_metrics WHERE workflow_id = %s ORDER BY created_at", (wid,))]
    assert stored == [t0 + timedelta(seconds=30), t0 + timedelta(seconds=50)]
    started, finished, wall = metrics.execute(
        "SELECT started_at, finished_at, wall_seconds FROM roletailor_ops.generations WHERE workflow_id = %s",
        (wid,)).fetchone()
    assert (started, finished) == (t0, t0 + timedelta(seconds=50))
    assert wall == pytest.approx(50.0)
