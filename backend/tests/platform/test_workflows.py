from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from roletailor import db
from roletailor.ai import gateway as gateway_module
from roletailor.pipeline import orchestrator
from tests.platform import stubs
from tests.platform.conftest import create_job, upload_resume


@pytest.fixture()
def stub_pipeline(monkeypatch):
    monkeypatch.setattr(orchestrator, "tailor", stubs.stub_tailor)
    monkeypatch.setattr(gateway_module, "build_gateway", stubs.stub_build_gateway)


def start(user, version_id, job_id, key=None, **extra):
    return user.post("/v1/workflows", json={"resume_version_id": version_id, "job_posting_id": job_id, **extra},
                     headers={"Idempotency-Key": key or str(uuid.uuid4())})


def count(org_id, sql, **params) -> int:
    with db.tenant_tx(org_id) as conn:
        return conn.execute(text(sql), params).scalar_one()


def test_consent_required(make_user, classic_docx):
    user = make_user(consent=False)
    version = upload_resume(user, classic_docx)["version"]
    r = start(user, version["id"], create_job(user)["id"])
    assert r.status_code == 428 and r.json()["error"]["code"] == "consent_required"


def test_full_workflow_review_export_share(make_user, classic_docx, stub_pipeline, client):
    user = make_user()
    version = upload_resume(user, classic_docx)["version"]
    job = create_job(user)
    key = str(uuid.uuid4())
    r = start(user, version["id"], job["id"], key=key)
    assert r.status_code == 202, r.text
    workflow = r.json()
    assert workflow["status"] == "completed"  # eager Celery

    assert start(user, version["id"], job["id"], key=key).json()["id"] == workflow["id"]  # idempotent replay
    conflict = start(user, version["id"], create_job(user)["id"], key=key)
    assert conflict.status_code == 409

    detail = user.get(f"/v1/workflows/{workflow['id']}").json()
    assert detail["workflow"]["target_role"] == "Senior Data Engineer"
    latest = detail["latest"]
    assert latest["iteration"] == 1 and float(latest["ats_score"]) == 78
    assert detail["scores_before"]["ats"] == 55 and detail["gaps"] == ["Terraform"]
    assert detail["feedback"]["overall"] == 72 and "Not a prediction" in detail["feedback"]["label"]
    assert len(detail["changes"]) == 2 and all(c["decision"] == "pending" for c in detail["changes"])

    org = user.org_id
    assert count(org, "SELECT count(*) FROM usage_tracking WHERE workflow_id = :w AND charge_type = 'free'",
                 w=workflow["id"]) == 1
    assert count(org, "SELECT count(*) FROM validation_results WHERE workflow_id = :w AND ai_metric_id IS NOT NULL",
                 w=workflow["id"]) == 1
    assert count(org, "SELECT count(*) FROM resume_versions WHERE content->'structure' <> 'null'"
                 " AND id = :v", v=version["id"]) == 1
    with db.tenant_tx(org) as conn:
        cached = conn.execute(text("SELECT structured_requirements FROM job_postings WHERE id = :j"),
                              {"j": job["id"]}).scalar_one()
    assert cached["_description_sha256"] and cached["title"] == "Senior Data Engineer"

    dashboard = user.get("/v1/workflows").json()
    assert dashboard[0]["id"] == workflow["id"] and dashboard[0]["company"] == "Contoso"

    # Review: reject one change; the export must keep the original text for it.
    rejected, accepted = detail["changes"]
    gid = latest["id"]
    r = user.patch(f"/v1/generated/{gid}/changes/{rejected['id']}", json={"decision": "rejected"})
    assert r.json()["decision"] == "rejected" and r.json()["decided_at"]
    assert user.post(f"/v1/generated/{gid}/approve").json()["approved_at"]

    export = user.post(f"/v1/generated/{gid}/exports", json={"kind": "docx"})
    assert export.status_code == 201, export.text
    download = client.get(export.json()["download_url"].removeprefix("http://localhost:8000"))
    assert download.status_code == 200
    from roletailor.documents import read_docx

    texts = [b.text for b in read_docx(download.content).blocks]
    assert accepted["proposed_text"] in texts and rejected["prior_text"] in texts
    assert rejected["proposed_text"] not in texts

    for kind in ("ats_report", "feedback_report"):
        assert user.post(f"/v1/generated/{gid}/exports", json={"kind": kind}).status_code == 201

    share = user.post(f"/v1/exports/{export.json()['export_id']}/share", json={"expires_in_hours": 72})
    assert share.status_code == 201
    public = client.get(share.json()["url"].removeprefix("http://localhost:8000"), follow_redirects=False)
    assert public.status_code == 302 and "/v1/files/" in public.headers["location"]
    assert client.get("/v1/share/not-a-real-token", follow_redirects=False).status_code == 404

    # Iterations never charge and build on the previous output.
    it = user.post(f"/v1/workflows/{workflow['id']}/iterations", json={"focus_block_ids": [accepted["block_path"]]})
    assert it.status_code == 202, it.text
    detail2 = user.get(f"/v1/workflows/{workflow['id']}").json()
    assert detail2["latest"]["iteration"] == 2 and detail2["workflow"]["status"] == "completed"
    assert count(org, "SELECT count(*) FROM usage_tracking WHERE workflow_id = :w", w=workflow["id"]) == 1
    assert "it2" in detail2["changes"][0]["proposed_text"] and "it1" in detail2["changes"][0]["prior_text"]

    actions = {r[0] for r in db_rows(org, "SELECT action FROM audit_logs")}
    assert {"resume.upload", "workflow.created", "workflow.completed", "export.created", "export.shared"} <= actions


def db_rows(org_id, sql):
    with db.tenant_tx(org_id) as conn:
        return conn.execute(text(sql)).all()


def test_failure_marks_failed_without_charge(make_user, classic_docx, monkeypatch):
    def broken(**kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(orchestrator, "tailor", broken)
    monkeypatch.setattr(gateway_module, "build_gateway", stubs.stub_build_gateway)
    user = make_user()
    version = upload_resume(user, classic_docx)["version"]
    workflow = start(user, version["id"], create_job(user)["id"]).json()
    assert workflow["status"] == "failed"
    detail = user.get(f"/v1/workflows/{workflow['id']}").json()
    assert "Nothing was charged" in detail["workflow"]["recovery_message"]
    assert count(user.org_id, "SELECT count(*) FROM usage_tracking") == 0
    assert count(user.org_id, "SELECT count(*) FROM audit_logs WHERE action = 'workflow.failed'") == 1

    # Recovery: /resume retries the pending run.
    monkeypatch.setattr(orchestrator, "tailor", stubs.stub_tailor)
    assert user.post(f"/v1/workflows/{workflow['id']}/resume").json()["status"] == "queued"
    assert user.get(f"/v1/workflows/{workflow['id']}").json()["workflow"]["status"] == "completed"


def test_transient_failure_retries_then_fails(make_user, classic_docx, monkeypatch):
    calls = []

    def unavailable(**kwargs):
        calls.append(1)
        raise gateway_module.AIUnavailable("it1:plan", "provider down")

    monkeypatch.setattr(orchestrator, "tailor", unavailable)
    monkeypatch.setattr(gateway_module, "build_gateway", stubs.stub_build_gateway)
    monkeypatch.setattr("roletailor.worker.tasks._backoff_seconds", lambda retries: 0)
    user = make_user()
    version = upload_resume(user, classic_docx)["version"]
    workflow = start(user, version["id"], create_job(user)["id"]).json()
    assert len(calls) == 3  # first try + 2 retries
    detail = user.get(f"/v1/workflows/{workflow['id']}").json()
    assert detail["workflow"]["status"] == "failed"
    assert detail["workflow"]["draft_state"]["error"]["code"] == "ai_unavailable"
    assert count(user.org_id, "SELECT count(*) FROM usage_tracking") == 0


def test_pause_resume_cancel(make_user, classic_docx, stub_pipeline, monkeypatch):
    user = make_user()
    version = upload_resume(user, classic_docx)["version"]
    monkeypatch.setattr("roletailor.services.workflows._enqueue", lambda *a: None)  # keep it queued
    workflow = start(user, version["id"], create_job(user)["id"]).json()
    assert workflow["status"] == "queued"
    wid = workflow["id"]
    assert user.post(f"/v1/workflows/{wid}/pause").json()["status"] == "paused"
    assert user.post(f"/v1/workflows/{wid}/pause").status_code == 409
    assert user.post(f"/v1/workflows/{wid}/resume").json()["status"] == "queued"
    assert user.post(f"/v1/workflows/{wid}/cancel").json()["status"] == "cancelled"
    # A late task delivery for a cancelled workflow does nothing.
    from roletailor.services import tailoring_runner

    assert tailoring_runner.run(user.org_id, wid, 1) == "skipped"


def test_real_pipeline_in_fake_mode_persists_everything(make_user, classic_docx):
    """End to end with the real tailor() and build_gateway() (RT_LLM_MODE=fake)."""
    user = make_user()
    version = upload_resume(user, classic_docx)["version"]
    r = start(user, version["id"], create_job(user)["id"])
    assert r.status_code == 202, r.text
    wid = r.json()["id"]
    detail = user.get(f"/v1/workflows/{wid}").json()
    assert detail["workflow"]["status"] == "completed", detail["workflow"]
    org = user.org_id
    for table in ("ai_metrics", "validation_results", "generated_resumes", "usage_tracking"):
        assert count(org, f"SELECT count(*) FROM {table} WHERE workflow_id = :w", w=wid) > 0, table
    assert count(org, "SELECT count(*) FROM resume_changes c JOIN generated_resumes g"
                 " ON g.id = c.generated_resume_id WHERE g.workflow_id = :w", w=wid) > 0
    with db.global_tx() as conn:
        assert conn.execute(text("SELECT count(*) FROM ai_model_versions")).scalar_one() > 0
        assert conn.execute(text("SELECT count(*) FROM prompt_versions WHERE environment = 'test'")).scalar_one() > 0
    assert detail["latest"]["simulated_feedback"]["label"].startswith("AI simulation")
