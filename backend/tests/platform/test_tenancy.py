"""RLS proves tenant isolation below the API, and the API never leaks across orgs."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from roletailor import db
from tests.platform.conftest import upload_resume


def test_org_cannot_read_another_orgs_resume_even_by_id(make_user, classic_docx):
    alice, bob = make_user(), make_user()
    resume = upload_resume(alice, classic_docx)["resume"]

    assert bob.get(f"/v1/resumes/{resume['id']}").status_code == 404
    assert all(r["id"] != resume["id"] for r in bob.get("/v1/resumes").json())
    assert alice.get(f"/v1/resumes/{resume['id']}").status_code == 200

    with db.tenant_tx(bob.org_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM resumes WHERE id = :id"),
                            {"id": resume["id"]}).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM resume_versions WHERE resume_id = :id"),
                            {"id": resume["id"]}).scalar_one() == 0
    with db.tenant_tx(alice.org_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM resumes WHERE id = :id"),
                            {"id": resume["id"]}).scalar_one() == 1


def test_no_tenant_context_sees_nothing(make_user, classic_docx):
    alice = make_user()
    upload_resume(alice, classic_docx)
    with db.global_tx() as conn:
        assert conn.execute(text("SELECT count(*) FROM resumes")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM organizations")).scalar_one() == 0


def test_cannot_write_rows_into_another_org(make_user):
    alice, bob = make_user(), make_user()
    with pytest.raises(DBAPIError, match="row-level security"), db.tenant_tx(bob.org_id) as conn:
        conn.execute(text("INSERT INTO job_postings (organization_id, description) VALUES (:org, 'x')"),
                     {"org": alice.org_id})


def test_membership_lookup_function_only_returns_the_given_user(make_user):
    alice = make_user()
    with db.global_tx() as conn:
        rows = conn.execute(text("SELECT * FROM roletailor.user_memberships(:u)"), {"u": alice.id}).all()
    assert [(str(r.organization_id), r.role) for r in rows] == [(alice.org_id, "owner")]
