"""Scanned PDFs: stored at upload, read by OCR in a worker task, retryable when that fails."""

from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfWriter
from sqlalchemy import text

from roletailor import db
from roletailor.documents import sandbox
from roletailor.documents.model import Block, ParsedDocument
from roletailor.documents.ocr import ocr_available
from roletailor.documents.pdf import soffice_path
from roletailor.services import resume_ocr
from roletailor.worker import tasks
from tests.documents.pdf_helpers import helvetica_pdf
from tests.documents.scans import scanned_pdf
from tests.platform.conftest import upload_resume

needs_ocr = pytest.mark.skipif(
    not ocr_available() or soffice_path() is None, reason="tesseract or LibreOffice not installed")


def _blank_pdf(pages: int = 1) -> bytes:
    """A PDF without a text layer (what the request path sees of any scan)."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def _upload(user, data: bytes):
    return user.post("/v1/resumes", files={"file": ("scan.pdf", data, "application/pdf")},
                     data={"name": "Scan"})


def _fake_doc(blocks: bool = True, **layout) -> ParsedDocument:
    return ParsedDocument(
        source_format="pdf", supports_in_place_edit=False,
        blocks=[Block(id="l0", kind="text_line", text="Ada Lovelace"),
                Block(id="l1", kind="text_line", text="Analytical engines", is_list_item=True)] if blocks else [],
        layout_metadata={"page_count": 1, **({"ocr": True, "ocr_mean_confidence": 91.5} if blocks else {}), **layout},
        findings=[{"code": "ocr_applied", "detail": "Text was read with OCR"}] if blocks
        else [{"code": "scanned_pdf_needs_ocr", "detail": "needs OCR"}],
    )


@pytest.fixture()
def queued(monkeypatch) -> list[tuple]:
    """Capture enqueued OCR jobs instead of running them (tests run Celery eagerly)."""
    calls: list[tuple] = []
    monkeypatch.setattr(tasks.ocr_resume, "apply_async",
                        lambda args=None, kwargs=None, **_: calls.append((tuple(args), kwargs)))
    return calls


def _run_task(user, resume_id: str) -> str:
    return tasks.ocr_resume.apply(args=[user.org_id, resume_id]).get()


def _scan(user, queued) -> str:
    r = _upload(user, _blank_pdf())
    assert r.status_code == 202, r.text
    return r.json()["resume"]["id"]


def _row(user, resume_id: str) -> dict:
    with db.tenant_tx(user.org_id) as conn:
        return dict(conn.execute(
            text("SELECT processing_status, processing_error, processing_started_at, processing_file_id,"
                 " (SELECT count(*) FROM resume_versions WHERE resume_id = resumes.id) AS versions"
                 " FROM resumes WHERE id = :id"), {"id": resume_id}).mappings().one())


def _audit_actions(user, resume_id: str) -> list[str]:
    with db.tenant_tx(user.org_id) as conn:
        return [r[0] for r in conn.execute(
            text("SELECT action FROM audit_logs WHERE resource_id = :id ORDER BY created_at"),
            {"id": resume_id})]


def test_text_pdf_and_docx_keep_the_fast_path(make_user, classic_docx, queued):
    user = make_user()
    for data, name in ((classic_docx, "r.docx"), (helvetica_pdf(), "r.pdf")):
        r = user.post("/v1/resumes", files={"file": (name, data, "application/octet-stream")})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["version"]["version_number"] == 1 and body["version"]["blocks"]
        assert body["resume"]["processing"] is None
        assert "processing_status" not in body["resume"] and "processing_file_id" not in body["resume"]
    assert queued == []


def test_scanned_upload_is_accepted_and_processing(make_user, queued):
    user = make_user()
    r = _upload(user, _blank_pdf())
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["version"] is None
    processing = body["resume"]["processing"]
    assert processing["status"] == "processing" and processing["error"] is None and processing["started_at"]
    rid = body["resume"]["id"]
    assert queued == [((user.org_id, rid), {"correlation": queued[0][1]["correlation"]})]

    listing = user.get("/v1/resumes").json()
    assert listing[0]["id"] == rid and listing[0]["latest_version"] is None
    assert listing[0]["processing"]["status"] == "processing"
    detail = user.get(f"/v1/resumes/{rid}").json()
    assert detail["versions"] == [] and detail["processing"]["status"] == "processing"
    assert user.patch(f"/v1/resumes/{rid}", json={"name": "Renamed"}).json()["processing"]["status"] == "processing"
    assert _audit_actions(user, rid) == ["resume.upload"]
    with db.tenant_tx(user.org_id) as conn:
        meta = conn.execute(text("SELECT metadata FROM audit_logs WHERE resource_id = :id"), {"id": rid}).scalar_one()
    assert meta["ocr"] == "queued"


def test_ready_resumes_have_no_processing(make_user, classic_docx):
    user = make_user()
    rid = upload_resume(user, classic_docx)["resume"]["id"]
    assert user.get("/v1/resumes").json()[0]["processing"] is None
    assert user.get(f"/v1/resumes/{rid}").json()["processing"] is None
    assert user.patch(f"/v1/resumes/{rid}", json={"name": "x"}).json()["processing"] is None
    guided = user.post("/v1/resumes/text", json={"text": "Ada Lovelace\n" + "Built engines and wrote notes. " * 30})
    assert guided.status_code == 201 and guided.json()["resume"]["processing"] is None


def test_task_completes_the_resume(make_user, queued, monkeypatch):
    user = make_user()
    rid = _scan(user, queued)
    file_id = str(_row(user, rid)["processing_file_id"])
    monkeypatch.setattr(resume_ocr, "_parse", lambda data: _fake_doc())
    assert _run_task(user, rid) == "ready"

    detail = user.get(f"/v1/resumes/{rid}").json()
    assert detail["processing"] is None and len(detail["versions"]) == 1
    version = user.get(f"/v1/resumes/{rid}/versions/{detail['versions'][0]['id']}").json()
    assert version["version_number"] == 1 and version["source_file_id"] == file_id
    assert version["source_format"] == "pdf" and [b["id"] for b in version["blocks"]] == ["l0", "l1"]
    assert "ocr_applied" in [f["code"] for f in version["findings"]]
    row = _row(user, rid)
    assert row["processing_status"] is None and row["processing_file_id"] is None
    assert user.get("/v1/resumes").json()[0]["latest_version"]["version_number"] == 1
    assert _audit_actions(user, rid) == ["resume.upload", "resume.ocr_completed"]
    with db.tenant_tx(user.org_id) as conn:
        meta = conn.execute(text("SELECT metadata FROM audit_logs WHERE action = 'resume.ocr_completed'"
                                 " AND resource_id = :id"), {"id": rid}).scalar_one()
    assert meta == {"pages": 1, "blocks": 2, "mean_confidence": 91.5}  # never any resume text


def test_task_is_idempotent(make_user, queued, monkeypatch):
    user = make_user()
    rid = _scan(user, queued)
    calls = []
    monkeypatch.setattr(resume_ocr, "_parse", lambda data: calls.append(1) or _fake_doc())
    assert [_run_task(user, rid), _run_task(user, rid)] == ["ready", "skipped"]
    assert len(calls) == 1 and _row(user, rid)["versions"] == 1


def test_archived_resume_is_skipped(make_user, queued, monkeypatch):
    user = make_user()
    rid = _scan(user, queued)
    assert user.delete(f"/v1/resumes/{rid}").status_code == 204
    monkeypatch.setattr(resume_ocr, "_parse", lambda data: pytest.fail("must not parse"))
    assert _run_task(user, rid) == "skipped"
    assert _row(user, rid)["versions"] == 0


def test_archived_while_ocr_runs_is_discarded(make_user, queued, monkeypatch):
    user = make_user()
    rid = _scan(user, queued)

    def archive_then_read(data):
        assert user.delete(f"/v1/resumes/{rid}").status_code == 204
        return _fake_doc()

    monkeypatch.setattr(resume_ocr, "_parse", archive_then_read)
    assert _run_task(user, rid) == "skipped" and _row(user, rid)["versions"] == 0


@pytest.mark.parametrize(("failure", "outcome", "code", "message"), [
    (_fake_doc(False, ocr_outcome="no_text"), "no_text", "ocr_no_text",
     "We could not find any text in this scan. Try a clearer scan, a DOCX, or paste the text."),
    (_fake_doc(False, ocr_outcome="timeout"), "timeout", "ocr_timeout",
     "Reading this scan took too long. Try again, or upload a DOCX or paste the text."),
    (_fake_doc(False, ocr_outcome="failed"), "failed", "ocr_failed",
     "We could not read this scan. Try again, or upload a DOCX or paste the text."),
    (_fake_doc(False), "failed", "ocr_failed", None),
    (sandbox.ParseTimeout("timed out"), "timeout", "ocr_timeout", None),
    (sandbox.ParseFailed("crashed"), "failed", "ocr_failed", None),
    (sandbox.DocumentRejected("too many paragraphs"), "failed", "ocr_failed", None),
])
def test_failures_are_stored_with_a_code(make_user, queued, monkeypatch, failure, outcome, code, message):
    user = make_user()
    rid = _scan(user, queued)

    def parse(data):
        if isinstance(failure, Exception):
            raise failure
        return failure

    monkeypatch.setattr(resume_ocr, "_parse", parse)
    assert _run_task(user, rid) == outcome
    processing = user.get(f"/v1/resumes/{rid}").json()["processing"]
    assert processing["status"] == "failed" and processing["error"]["code"] == code
    if message:
        assert processing["error"]["message"] == message
    assert user.get("/v1/resumes").json()[0]["processing"]["error"]["code"] == code
    row = _row(user, rid)
    assert row["processing_file_id"] is not None and row["versions"] == 0  # kept for a retry
    assert _audit_actions(user, rid)[-1] == "resume.ocr_failed"


def test_transient_errors_are_retried_then_fail(make_user, queued, monkeypatch):
    user = make_user()
    rid = _scan(user, queued)
    attempts = []

    def busy(data):
        attempts.append(1)
        raise sandbox.ParserBusy("busy")

    monkeypatch.setattr(resume_ocr, "_parse", busy)
    assert _run_task(user, rid) == "failed"
    assert len(attempts) == 3  # first run plus two retries
    assert user.get(f"/v1/resumes/{rid}").json()["processing"]["error"]["code"] == "ocr_failed"


def test_transient_error_then_success(make_user, queued, monkeypatch):
    user = make_user()
    rid = _scan(user, queued)
    results = [sandbox.ParserBusy("busy"), _fake_doc()]

    def parse(data):
        item = results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(resume_ocr, "_parse", parse)
    assert _run_task(user, rid) == "ready"


def test_unexpected_errors_fail_without_retrying(make_user, queued, monkeypatch):
    user = make_user()
    rid = _scan(user, queued)
    attempts = []

    def broken(data):
        attempts.append(1)
        raise RuntimeError("bug")

    monkeypatch.setattr(resume_ocr, "_parse", broken)
    assert _run_task(user, rid) == "failed" and len(attempts) == 1
    assert user.get(f"/v1/resumes/{rid}").json()["processing"]["error"]["code"] == "ocr_failed"


def _age(user, rid: str, seconds: int) -> None:
    with db.tenant_tx(user.org_id) as conn:
        conn.execute(text("UPDATE resumes SET processing_started_at = now() - make_interval(secs => :s)"
                          " WHERE id = :id"), {"s": seconds, "id": rid})


def test_stale_processing_reads_as_failed_without_a_write(make_user, queued):
    user = make_user()
    rid = _scan(user, queued)
    _age(user, rid, 3600)
    for processing in (user.get(f"/v1/resumes/{rid}").json()["processing"],
                       user.get("/v1/resumes").json()[0]["processing"]):
        assert processing["status"] == "failed" and processing["error"]["code"] == "ocr_timeout"
    assert _row(user, rid)["processing_status"] == "processing"  # computed at read time only


def test_stale_resume_can_be_retried_and_an_old_attempt_cannot_fail_the_new_one(make_user, queued):
    user = make_user()
    rid = _scan(user, queued)
    _age(user, rid, 3600)
    old_start = _row(user, rid)["processing_started_at"]
    assert user.post(f"/v1/resumes/{rid}/processing/retry").status_code == 202
    assert user.get(f"/v1/resumes/{rid}").json()["processing"]["status"] == "processing"
    assert resume_ocr.mark_failed(user.org_id, rid, "failed", old_start) is False
    assert _row(user, rid)["processing_status"] == "processing"


def test_retry_runs_ocr_again(make_user, queued, monkeypatch):
    user = make_user()
    rid = _scan(user, queued)
    monkeypatch.setattr(resume_ocr, "_parse", lambda data: _fake_doc(False, ocr_outcome="no_text"))
    assert _run_task(user, rid) == "no_text"
    queued.clear()

    r = user.post(f"/v1/resumes/{rid}/processing/retry")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["id"] == rid and body["versions"] == []
    assert body["processing"]["status"] == "processing" and body["processing"]["error"] is None
    assert len(queued) == 1 and queued[0][0] == (user.org_id, rid)
    assert _audit_actions(user, rid)[-1] == "resume.ocr_retry"

    monkeypatch.setattr(resume_ocr, "_parse", lambda data: _fake_doc())
    assert _run_task(user, rid) == "ready"
    assert user.get(f"/v1/resumes/{rid}").json()["processing"] is None


def test_retry_is_refused_unless_failed(make_user, queued, classic_docx):
    user = make_user()
    rid = _scan(user, queued)
    r = user.post(f"/v1/resumes/{rid}/processing/retry")  # still processing, not stale
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_retryable"
    ready = upload_resume(user, classic_docx)["resume"]["id"]
    r = user.post(f"/v1/resumes/{ready}/processing/retry")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_retryable"
    assert len(queued) == 1  # only the upload was enqueued


def test_retry_is_refused_for_an_archived_resume(make_user, queued, monkeypatch):
    user = make_user()
    rid = _scan(user, queued)
    monkeypatch.setattr(resume_ocr, "_parse", lambda data: _fake_doc(False, ocr_outcome="failed"))
    _run_task(user, rid)
    user.delete(f"/v1/resumes/{rid}")
    assert user.post(f"/v1/resumes/{rid}/processing/retry").status_code == 409


def test_other_users_cannot_retry(make_user, queued, monkeypatch):
    owner, other = make_user(), make_user()
    rid = _scan(owner, queued)
    monkeypatch.setattr(resume_ocr, "_parse", lambda data: _fake_doc(False, ocr_outcome="failed"))
    _run_task(owner, rid)
    r = other.post(f"/v1/resumes/{rid}/processing/retry")
    assert r.status_code == 404
    assert other.get(f"/v1/resumes/{rid}").status_code == 404
    assert _row(owner, rid)["processing_status"] == "failed"
    # the task does nothing for an organisation that does not own the row
    assert tasks.ocr_resume.apply(args=[other.org_id, rid]).get() == "skipped"


def test_scan_with_too_many_pages_is_refused(make_user, queued):
    user = make_user()
    r = _upload(user, _blank_pdf(7))
    assert r.status_code == 422 and r.json()["error"]["code"] == "scanned_pdf_too_long"
    assert r.json()["error"]["message"] == (
        "This PDF is a scan with 7 pages. We can read scanned resumes of up to 6 pages. "
        "Upload a shorter scan, a DOCX, or paste the text.")
    assert user.get("/v1/resumes").json() == [] and queued == []
    with db.tenant_tx(user.org_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM stored_files")).scalar_one() == 0


def test_broker_failure_marks_the_resume_unavailable(make_user, monkeypatch):
    def down(*args, **kwargs):
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks.ocr_resume, "apply_async", down)
    user = make_user()
    r = _upload(user, _blank_pdf())
    assert r.status_code == 202, r.text
    processing = r.json()["resume"]["processing"]
    assert processing["status"] == "failed" and processing["error"] == {
        "code": "ocr_unavailable", "message": "We could not start reading this scan. Try again in a moment."}
    rid = r.json()["resume"]["id"]
    assert user.get(f"/v1/resumes/{rid}").json()["processing"]["error"]["code"] == "ocr_unavailable"
    monkeypatch.undo()  # broker is back: retry (eagerly run, with no Tesseract result patched)
    monkeypatch.setattr(resume_ocr, "_parse", lambda data: _fake_doc())
    assert user.post(f"/v1/resumes/{rid}/processing/retry").status_code == 202
    assert user.get(f"/v1/resumes/{rid}").json()["processing"] is None


def test_ocr_disabled_keeps_the_old_behaviour(make_user, queued, monkeypatch):
    from roletailor.config import get_settings

    monkeypatch.setattr(get_settings(), "ocr_enabled", False)
    user = make_user()
    r = _upload(user, _blank_pdf())
    assert r.status_code == 201
    body = r.json()
    assert body["resume"]["processing"] is None and body["version"]["blocks"] == []
    assert [f["code"] for f in body["version"]["findings"]] == ["scanned_pdf_needs_ocr"]
    assert queued == []


def test_archiving_a_failed_resume_works(make_user, queued, monkeypatch):
    user = make_user()
    rid = _scan(user, queued)
    monkeypatch.setattr(resume_ocr, "_parse", lambda data: _fake_doc(False, ocr_outcome="failed"))
    _run_task(user, rid)
    assert user.delete(f"/v1/resumes/{rid}").status_code == 204
    assert user.get("/v1/resumes").json() == []


def test_a_resume_without_versions_does_not_break_other_views(make_user, queued):
    user = make_user()
    _scan(user, queued)
    assert user.get("/v1/workflows").json() == []  # the dashboard joins through versions
    export = user.get("/v1/me/export")
    assert export.status_code == 200
    assert len(export.json()["organizations"][0]["data"]["resumes"]) == 1


@needs_ocr
def test_scan_upload_is_read_end_to_end(make_user):
    """No patching: the upload is queued, the (eager) task OCRs it in the sandbox."""
    user = make_user()
    r = _upload(user, scanned_pdf(1))
    assert r.status_code == 202, r.text
    assert r.json()["version"] is None and r.json()["resume"]["processing"]["status"] == "processing"
    rid = r.json()["resume"]["id"]
    detail = user.get(f"/v1/resumes/{rid}").json()
    assert detail["processing"] is None and len(detail["versions"]) == 1
    version = user.get(f"/v1/resumes/{rid}/versions/{detail['versions'][0]['id']}").json()
    assert version["blocks"][0]["text"] == "Priya Raman"
    assert "ocr_applied" in [f["code"] for f in version["findings"]]
    assert version["layout_metadata"]["ocr"] is True
