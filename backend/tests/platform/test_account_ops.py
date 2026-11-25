from __future__ import annotations

from sqlalchemy import text

from roletailor import db
from tests.platform.conftest import upload_resume


def test_applications_crud(make_user):
    user = make_user()
    created = user.post("/v1/applications", json={"company": "Contoso", "role_title": "Data Engineer"})
    assert created.status_code == 201 and created.json()["status"] == "saved"
    aid = created.json()["id"]
    assert user.patch(f"/v1/applications/{aid}", json={"status": "applied"}).json()["status"] == "applied"
    assert [a["id"] for a in user.get("/v1/applications").json()] == [aid]
    bad = user.post("/v1/applications", json={"company": "X", "role_title": "Y",
                                               "job_posting_id": "00000000-0000-0000-0000-000000000000"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_reference"
    assert user.delete(f"/v1/applications/{aid}").status_code == 204
    assert user.get(f"/v1/applications/{aid}").status_code == 404


def test_data_export_and_account_deletion(client, make_user, classic_docx):
    from roletailor.config import get_settings

    user = make_user()
    upload_resume(user, classic_docx)
    export = user.get("/v1/me/export").json()
    assert export["user"]["email"] == user.email
    assert len(export["organizations"][0]["data"]["resumes"]) == 1
    files_dir = get_settings().storage_local_dir / user.org_id
    assert any(files_dir.rglob("*.docx"))

    assert user.delete("/v1/me").status_code == 202
    assert user.get("/v1/me").status_code == 401
    login = client.post("/v1/auth/login", json={"email": user.email, "password": "correct horse battery"})
    assert login.status_code == 401
    assert not any(files_dir.rglob("*.docx"))
    with db.tenant_tx(user.org_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM organizations")).scalar_one() == 0
    with db.global_tx() as conn:
        assert conn.execute(text("SELECT count(*) FROM users WHERE id = :id"), {"id": user.id}).scalar_one() == 0


def test_ops_endpoints(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz")
    assert ready.json()["checks"]["database"] == "ok"
    client.get("/v1/me")
    metrics = client.get("/metrics").text
    assert 'roletailor_http_requests_total{method="GET",route="/v1/me",status="401"}' in metrics
