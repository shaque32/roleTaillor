from __future__ import annotations

import httpx
import pytest

from roletailor.services import job_fetch
from tests.platform.conftest import create_job, upload_resume

GUIDED = {
    "name": "Guided resume",
    "contact": {"full_name": "Ada Lovelace", "email": "ada@example.com", "links": ["https://ada.dev"]},
    "sections": [
        {"kind": "summary", "title": "Summary", "items": [{"text": "Data engineer with 7 years in streaming."}]},
        {"kind": "experience", "title": "Experience", "items": [
            {"company": "Northwind", "title": "Senior Data Engineer", "start": "2021", "end": "Present",
             "bullets": ["Built Kafka pipelines serving 40M events/day."]}]},
        {"kind": "education", "title": "Education", "items": [
            {"institution": "University of London", "degree": "BSc", "field": "Mathematics", "end": "2015"}]},
        {"kind": "skills", "title": "Skills", "items": [{"text": "Python, SQL, Spark"}]},
    ],
}


def test_upload_docx_creates_version_with_blocks(make_user, classic_docx):
    user = make_user()
    body = upload_resume(user, classic_docx)
    version = body["version"]
    assert body["resume"]["origin"] == "upload"
    assert version["source_format"] == "docx" and version["version_number"] == 1
    assert any("Kafka" in b["text"] for b in version["blocks"])
    assert isinstance(version["findings"], list) and isinstance(version["layout_metadata"], dict)

    listing = user.get("/v1/resumes").json()
    assert listing[0]["latest_version"]["id"] == version["id"]

    rid = body["resume"]["id"]
    restored = user.post(f"/v1/resumes/{rid}/versions/{version['id']}/restore").json()
    assert restored["version_number"] == 2 and restored["parent_version_id"] == version["id"]
    assert user.get(f"/v1/resumes/{rid}/versions/{restored['id']}").json()["blocks"] == version["blocks"]
    assert len(user.get(f"/v1/resumes/{rid}").json()["versions"]) == 2

    assert user.patch(f"/v1/resumes/{rid}", json={"name": "Renamed"}).json()["name"] == "Renamed"
    assert user.delete(f"/v1/resumes/{rid}").status_code == 204
    assert user.get("/v1/resumes").json() == []


@pytest.mark.parametrize(("data", "status", "code"), [
    (b"hello, plain text", 415, "unsupported_file_type"),
    (b"PK\x03\x04not really a docx", 415, "unsupported_file_type"),
    (b"", 415, "file_empty"),
])
def test_upload_rejects_other_types(make_user, data, status, code):
    user = make_user()
    r = user.post("/v1/resumes", files={"file": ("resume.docx", data, "application/pdf")})
    assert r.status_code == status and r.json()["error"]["code"] == code


def test_blocked_scan_is_rejected_and_recorded(make_user, classic_docx, monkeypatch):
    from sqlalchemy import text

    from roletailor import db
    from roletailor.storage import DevScanner

    monkeypatch.setattr(DevScanner, "scan", lambda self, data, media_type: "blocked")
    user = make_user()
    r = user.post("/v1/resumes", files={"file": ("r.docx", classic_docx, "application/octet-stream")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_blocked"
    with db.tenant_tx(user.org_id) as conn:  # rolled back with the request: nothing served, nothing kept
        assert conn.execute(text("SELECT count(*) FROM stored_files")).scalar_one() == 0


def test_guided_resume_renders_and_parses(make_user):
    user = make_user()
    r = user.post("/v1/resumes/guided", json=GUIDED)
    assert r.status_code == 201, r.text
    version = r.json()["version"]
    assert version["source_format"] == "guided"
    texts = [b["text"] for b in version["blocks"]]
    assert any("Kafka pipelines" in t for t in texts) and any("Ada Lovelace" in t for t in texts)


def test_job_from_paste_and_unreadable_url(make_user, monkeypatch):
    user = make_user()
    job = create_job(user)
    assert job["company"] == "Contoso"
    assert user.get(f"/v1/jobs/{job['id']}").json()["description"].startswith("Senior Data Engineer")

    def fail(*args, **kwargs):
        raise job_fetch.JobFetchError("blocked")

    monkeypatch.setattr(job_fetch, "fetch_job_page", fail)
    r = user.post("/v1/jobs", json={"source_url": "https://jobs.example.com/1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "job_url_unreadable"


@pytest.mark.parametrize("url", ["http://127.0.0.1/admin", "http://10.0.0.5/", "http://[::1]/",
                                 "file:///etc/passwd", "http://169.254.169.254/latest/meta-data"])
def test_ssrf_guard_rejects_private_targets(url):
    with pytest.raises(job_fetch.JobFetchError):
        job_fetch.fetch_job_page(url, timeout=1, max_bytes=1000)


LONG = "Build reliable data pipelines with Kafka and Spark. " * 10


def test_fetch_follows_redirects_and_rechecks(monkeypatch):
    addresses = {"jobs.example.com": "93.184.216.34", "internal.example.com": "192.168.1.10"}
    monkeypatch.setattr(job_fetch, "_resolve", lambda host, port: [addresses[host]])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/go-internal":
            return httpx.Response(302, headers={"location": "http://internal.example.com/"})
        if request.url.path == "/move":
            return httpx.Response(301, headers={"location": "/job"})
        html = (f"<html><head><title>Data Engineer</title></head><body><nav>menu</nav>"
                f"<main><h1>Data Engineer</h1><p>{LONG}</p></main><footer>x</footer></body></html>")
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    job = job_fetch.fetch_job_page("https://jobs.example.com/move", timeout=1, max_bytes=100_000, transport=transport)
    assert job.title == "Data Engineer" and "Kafka" in job.text and "menu" not in job.text
    with pytest.raises(job_fetch.JobFetchError, match="non-public"):
        job_fetch.fetch_job_page("https://jobs.example.com/go-internal", timeout=1, max_bytes=100_000,
                                 transport=transport)
    with pytest.raises(job_fetch.JobFetchError, match="too large"):
        job_fetch.fetch_job_page("https://jobs.example.com/job", timeout=1, max_bytes=100, transport=transport)


def test_extracts_json_ld_job_posting():
    html = ('<html><body><script type="application/ld+json">'
            '{"@context": "https://schema.org", "@type": "JobPosting", "title": "ML Engineer",'
            f' "hiringOrganization": {{"name": "Fabrikam"}}, "description": "<p>{LONG}</p>"}}'
            '</script></body></html>')
    job = job_fetch.extract_job(html)
    assert (job.title, job.company) == ("ML Engineer", "Fabrikam")
