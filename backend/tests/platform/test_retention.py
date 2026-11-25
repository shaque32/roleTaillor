"""Hard delete after the retention period, and per-plan run and iteration caps."""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import text

from roletailor import db
from roletailor.ai import gateway as gateway_module
from roletailor.config import Settings, get_settings
from roletailor.pipeline import orchestrator
from roletailor.services import retention
from roletailor.storage import get_storage
from tests.platform import stubs
from tests.platform.conftest import create_job, signed_webhook, stripe_event, upload_resume


@pytest.fixture()
def stub_pipeline(monkeypatch):
    monkeypatch.setattr(orchestrator, "tailor", stubs.stub_tailor)
    monkeypatch.setattr(gateway_module, "build_gateway", stubs.stub_build_gateway)


@pytest.fixture
def settings(monkeypatch):
    def apply(**values):
        for key, value in values.items():
            monkeypatch.setenv(f"RT_{key.upper()}", str(value))
        get_settings.cache_clear()

    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()


def start(user, version_id, job_id):
    return user.post("/v1/workflows", json={"resume_version_id": version_id, "job_posting_id": job_id},
                     headers={"Idempotency-Key": str(uuid.uuid4())})


def rows(org_id, sql, **params):
    with db.tenant_tx(org_id) as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def scalar(org_id, sql, **params):
    with db.tenant_tx(org_id) as conn:
        return conn.execute(text(sql), params).scalar_one()


def backdate(org_id, resume_id, days: int) -> None:
    with db.tenant_tx(org_id) as conn:
        conn.execute(text("UPDATE resumes SET archived_at = now() - make_interval(days => :d)"
                          " WHERE id = :id"), {"d": days, "id": resume_id})


def purge_only(org_id) -> retention.PurgeSummary:
    """Run the purge, then check it left no other test's organization half done."""
    summary = retention.purge_due()
    assert summary.failed == 0
    return summary


def tailored(user, classic_docx) -> dict:
    uploaded = upload_resume(user, classic_docx)
    job = create_job(user)
    workflow = start(user, uploaded["version"]["id"], job["id"]).json()
    assert workflow["status"] == "completed"
    detail = user.get(f"/v1/workflows/{workflow['id']}").json()
    export = user.post(f"/v1/generated/{detail['latest']['id']}/exports", json={"kind": "docx"}).json()
    share = user.post(f"/v1/exports/{export['export_id']}/share", json={"expires_in_hours": 72}).json()
    return {"resume": uploaded["resume"], "version": uploaded["version"], "workflow": workflow,
            "generated": detail["latest"], "export": export, "share": share, "job": job}


def test_deleted_resume_is_erased_after_the_retention_period(make_user, classic_docx, stub_pipeline, client):
    user = make_user()
    made = tailored(user, classic_docx)
    org, rid, wid = user.org_id, made["resume"]["id"], made["workflow"]["id"]
    application = user.post("/v1/applications", json={
        "company": "Contoso", "role_title": "Data Engineer", "resume_version_id": made["version"]["id"],
    }).json()
    objects = rows(org, "SELECT object_key, object_version FROM stored_files")
    assert len(objects) >= 3  # upload, generated file, export
    free_used = user.get("/v1/billing/status").json()["free_used"]
    assert free_used == 1

    assert user.delete(f"/v1/resumes/{rid}").status_code == 204
    backdate(org, rid, 29)
    purge_only(org)
    assert scalar(org, "SELECT purged_at FROM resumes WHERE id = :id", id=rid) is None
    assert scalar(org, "SELECT content FROM resume_versions WHERE id = :id", id=made["version"]["id"])["blocks"]

    backdate(org, rid, 31)
    purge_only(org)

    # Content and files are gone.
    resume = rows(org, "SELECT name, purged_at FROM resumes WHERE id = :id", id=rid)[0]
    assert resume["purged_at"] is not None and resume["name"] == retention.PURGED_NAME
    versions = rows(org, "SELECT content, layout_metadata, extraction_findings, source_file_id"
                         " FROM resume_versions WHERE resume_id = :id", id=rid)
    assert len(versions) == 2
    assert all(v == {"content": {}, "layout_metadata": {}, "extraction_findings": [],
                     "source_file_id": None} for v in versions)
    assert scalar(org, "SELECT count(*) FROM stored_files") == 0
    storage = get_storage()
    for obj in objects:
        with pytest.raises(FileNotFoundError):
            storage.get(obj["object_key"], obj["object_version"])
    changes = rows(org, "SELECT prior_text, proposed_text, reason, prioritized_keywords FROM resume_changes")
    assert changes and all(c == {"prior_text": None, "proposed_text": None, "reason": None,
                                 "prioritized_keywords": []} for c in changes)
    assert scalar(org, "SELECT count(*) FROM generated_resumes WHERE simulated_feedback IS NOT NULL") == 0
    assert scalar(org, "SELECT count(*) FROM validation_results WHERE details <> '{}'") == 0
    assert scalar(org, "SELECT draft_state FROM tailoring_workflows WHERE id = :id", id=wid) == {}
    for table in ("resume_exports", "resume_share_links", "embeddings"):
        assert scalar(org, f"SELECT count(*) FROM {table}") == 0

    # The owner can no longer reach any of it.
    assert user.get(f"/v1/resumes/{rid}").status_code == 404
    assert user.get(f"/v1/resumes/{rid}/versions/{made['version']['id']}").status_code == 404
    assert user.get(f"/v1/workflows/{wid}").status_code == 404
    assert user.post(f"/v1/workflows/{wid}/iterations", json={}).status_code == 404
    assert user.post(f"/v1/generated/{made['generated']['id']}/exports", json={"kind": "docx"}).status_code == 404
    assert start(user, made["version"]["id"], made["job"]["id"]).status_code == 404
    assert user.get("/v1/workflows").json() == []
    share_path = made["share"]["url"].removeprefix("http://localhost:8000")
    assert client.get(share_path, follow_redirects=False).status_code == 404
    assert user.get(f"/v1/applications/{application['id']}").json()["resume_version_id"] is None

    # Billing still counts the generation that was used, and the purge is on the audit trail.
    assert user.get("/v1/billing/status").json()["free_used"] == free_used
    assert scalar(org, "SELECT count(*) FROM usage_tracking WHERE workflow_id = :w", w=wid) == 1
    audit_row = rows(org, "SELECT resource_id, metadata FROM audit_logs WHERE action = 'resume.purge'")[0]
    assert str(audit_row["resource_id"]) == rid and audit_row["metadata"]["files"] == len(objects)

    # An idempotent replay of the original request does not hand the workflow back.
    assert scalar(org, "SELECT count(*) FROM tailoring_workflows WHERE id = :id", id=wid) == 1
    key = scalar(org, "SELECT idempotency_key FROM tailoring_workflows WHERE id = :id", id=wid)
    replay = user.post("/v1/workflows", headers={"Idempotency-Key": key}, json={
        "resume_version_id": made["version"]["id"], "job_posting_id": made["job"]["id"]})
    assert replay.status_code == 404

    # Nothing left to do on the next night.
    with db.global_tx() as conn:
        due = conn.execute(text(
            "SELECT resume_id FROM roletailor.resumes_due_for_purge(interval '30 days', 1000)")).all()
    assert rid not in {str(r[0]) for r in due}


def test_purge_leaves_other_resumes_alone(make_user, classic_docx, stub_pipeline):
    user, other = make_user(), make_user()
    doomed = tailored(user, classic_docx)
    kept = upload_resume(user, classic_docx)  # same organization, not deleted
    recent = upload_resume(user, classic_docx)  # deleted yesterday
    theirs = upload_resume(other, classic_docx)  # another organization
    for rid in (doomed["resume"]["id"], recent["resume"]["id"]):
        assert user.delete(f"/v1/resumes/{rid}").status_code == 204
    backdate(user.org_id, doomed["resume"]["id"], 45)
    backdate(user.org_id, recent["resume"]["id"], 1)

    purge_only(user.org_id)

    assert user.get(f"/v1/resumes/{doomed['resume']['id']}").status_code == 404
    for owner, made in ((user, kept), (other, theirs)):
        version = owner.get(f"/v1/resumes/{made['resume']['id']}/versions/{made['version']['id']}")
        assert version.status_code == 200 and version.json()["blocks"]
    assert scalar(user.org_id, "SELECT purged_at FROM resumes WHERE id = :id", id=recent["resume"]["id"]) is None
    assert scalar(user.org_id, "SELECT count(*) FROM stored_files") == 2
    assert scalar(other.org_id, "SELECT count(*) FROM stored_files") == 1


def test_purge_waits_for_a_run_in_flight(make_user, classic_docx, stub_pipeline):
    user = make_user()
    made = tailored(user, classic_docx)
    org, rid, wid = user.org_id, made["resume"]["id"], made["workflow"]["id"]
    user.delete(f"/v1/resumes/{rid}")
    backdate(org, rid, 40)
    with db.tenant_tx(org) as conn:
        conn.execute(text("UPDATE tailoring_workflows SET status = 'running' WHERE id = :id"), {"id": wid})

    # Busy resumes are not candidates at all, so they cannot crowd out a small batch.
    with db.global_tx() as conn:
        due = conn.execute(text(
            "SELECT resume_id FROM roletailor.resumes_due_for_purge(interval '30 days', 100000)")).all()
    assert rid not in {str(r[0]) for r in due}
    # The locked check inside the purge still refuses it if it is offered anyway.
    with db.tenant_tx(org) as conn:
        assert retention._purge_resume(conn, org, rid, 30) is None
    purge_only(org)
    assert scalar(org, "SELECT purged_at FROM resumes WHERE id = :id", id=rid) is None
    assert scalar(org, "SELECT count(*) FROM stored_files") >= 3

    with db.tenant_tx(org) as conn:
        conn.execute(text("UPDATE tailoring_workflows SET status = 'completed' WHERE id = :id"), {"id": wid})
    purge_only(org)
    assert scalar(org, "SELECT purged_at FROM resumes WHERE id = :id", id=rid) is not None


def test_retention_floor_and_setting(make_user, classic_docx, settings):
    user = make_user()
    rid = upload_resume(user, classic_docx)["resume"]["id"]
    user.delete(f"/v1/resumes/{rid}")
    backdate(user.org_id, rid, 3)
    # The lookup never returns a resume deleted less than a day ago, whatever it is asked.
    with db.global_tx() as conn:
        due = conn.execute(text(
            "SELECT resume_id FROM roletailor.resumes_due_for_purge(interval '0', 1000)")).all()
    assert rid in {str(r[0]) for r in due}
    backdate(user.org_id, rid, 0)
    with db.global_tx() as conn:
        due = conn.execute(text(
            "SELECT resume_id FROM roletailor.resumes_due_for_purge(interval '0', 1000)")).all()
    assert rid not in {str(r[0]) for r in due}

    backdate(user.org_id, rid, 3)
    settings(resume_retention_days=2)
    purge_only(user.org_id)
    assert scalar(user.org_id, "SELECT purged_at FROM resumes WHERE id = :id", id=rid) is not None
    with pytest.raises(ValueError):
        Settings(resume_retention_days=0)


def test_purge_task_takes_a_lock(make_user, classic_docx, monkeypatch):
    import redis

    from roletailor.worker import tasks

    user = make_user()
    rid = upload_resume(user, classic_docx)["resume"]["id"]
    user.delete(f"/v1/resumes/{rid}")
    backdate(user.org_id, rid, 31)
    held = redis.Redis.from_url(get_settings().redis_url)
    held.set(tasks.PURGE_LOCK_KEY, "1", ex=60)
    try:
        assert tasks.purge_deleted_resumes.apply().get()["purged"] == 0
        assert scalar(user.org_id, "SELECT purged_at FROM resumes WHERE id = :id", id=rid) is None
    finally:
        held.delete(tasks.PURGE_LOCK_KEY)
    assert tasks.purge_deleted_resumes.apply().get()["purged"] >= 1
    assert scalar(user.org_id, "SELECT purged_at FROM resumes WHERE id = :id", id=rid) is not None
    assert held.get(tasks.PURGE_LOCK_KEY) is None


# --------------------------------------------------------------------------
# Per-plan caps
# --------------------------------------------------------------------------


def subscribe(client, user) -> None:
    with db.tenant_tx(user.org_id) as conn:
        customer = f"cus_{uuid.uuid4().hex[:10]}"
        conn.execute(text("UPDATE organizations SET stripe_customer_id = :c"), {"c": customer})
    sub = {"id": f"sub_{uuid.uuid4().hex[:10]}", "customer": customer, "status": "active",
           "cancel_at_period_end": False,
           "items": {"data": [{"price": {"id": "price_sub_test"},
                               "current_period_end": int(time.time()) + 86400}]}}
    body, headers = signed_webhook(stripe_event("customer.subscription.created", sub))
    assert client.post("/v1/billing/webhook", content=body, headers=headers).json()["status"] == "processed"


def test_plan_limits_setting_is_validated():
    s = Settings(generation_runs_per_org_per_day=60, max_iterations_per_workflow=15,
                 plan_limits={"subscription": {"runs_per_day": 200}})
    assert s.limits_for_plan("free") == (60, 15)
    assert s.limits_for_plan("subscription") == (200, 15)
    for bad in ({"enterprise": {"runs_per_day": 5}}, {"free": {"runs": 5}}, {"free": {"iterations": 0}}):
        with pytest.raises(ValueError):
            Settings(plan_limits=bad)


def test_iteration_cap_follows_the_plan(make_user, classic_docx, stub_pipeline, client, settings):
    user = make_user()
    made = tailored(user, classic_docx)
    iterate = f"/v1/workflows/{made['workflow']['id']}/iterations"
    settings(max_iterations_per_workflow=1, plan_limits='{"subscription": {"iterations": 2}}')

    refused = user.post(iterate, json={})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "iteration_limit"

    subscribe(client, user)
    assert user.post(iterate, json={}).status_code == 202
    assert user.post(iterate, json={}).status_code == 409  # the subscription cap is 2


def test_daily_run_cap_follows_the_plan(make_user, client, settings):
    free, paying = make_user(), make_user()
    subscribe(client, paying)
    settings(generation_runs_per_org_per_day=1, plan_limits='{"subscription": {"runs_per_day": 3}}')
    body = {"resume_version_id": "00000000-0000-0000-0000-000000000001",
            "job_posting_id": "00000000-0000-0000-0000-000000000002"}

    def codes(user, n):
        return [client.post("/v1/workflows", json=body, headers=user.headers).status_code for _ in range(n)]

    assert [c == 429 for c in codes(free, 2)] == [False, True]
    assert [c == 429 for c in codes(paying, 4)] == [False, False, False, True]


def test_failed_object_deletes_are_retried(make_user, classic_docx, monkeypatch):
    user = make_user()
    rid = upload_resume(user, classic_docx)["resume"]["id"]
    obj = rows(user.org_id, "SELECT object_key, object_version FROM stored_files")[0]
    user.delete(f"/v1/resumes/{rid}")
    backdate(user.org_id, rid, 31)
    storage = get_storage()
    real_delete = storage.delete

    def pending():
        with db.global_tx() as conn:
            return conn.execute(text("SELECT attempts FROM pending_object_deletions WHERE object_key = :k"),
                                {"k": obj["object_key"]}).all()

    def broken(key, version=None):
        if key == obj["object_key"]:
            raise OSError("object store unavailable")
        real_delete(key, version)

    monkeypatch.setattr(type(storage), "delete", lambda self, key, version=None: broken(key, version))
    summary = retention.purge_due()
    assert summary.objects_pending >= 1
    assert scalar(user.org_id, "SELECT purged_at FROM resumes WHERE id = :id", id=rid) is not None
    assert [r[0] for r in pending()] == [1]
    assert storage.get(obj["object_key"], obj["object_version"])  # still there, still queued

    monkeypatch.undo()
    retention.purge_due()  # the resume is no longer due; the queue alone drives the retry
    assert pending() == []
    with pytest.raises(FileNotFoundError):
        storage.get(obj["object_key"], obj["object_version"])
