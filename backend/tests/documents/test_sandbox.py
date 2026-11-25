"""The sandboxed parser: real child processes, real limits."""

from __future__ import annotations

import io
import zipfile

import pytest

from roletailor.documents import sandbox
from roletailor.documents.ocr import ocr_available
from roletailor.documents.pdf import soffice_path
from tests.fixtures import make_classic_resume

from .pdf_helpers import helvetica_pdf
from .scans import blank_scanned_pdf, scanned_pdf

LIMITS = {"timeout": 60, "memory_mb": 768, "cpu_seconds": 30, "max_pages": 20, "max_blocks": 3000}


def _docx_with_document(xml: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(make_classic_resume()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            target.writestr(info.filename, xml if info.filename == "word/document.xml" else source.read(info.filename))
    return out.getvalue()


def _bomb(paragraphs: int) -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = b"<w:p><w:r><w:t>aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa</w:t></w:r></w:p>" * paragraphs
    return _docx_with_document(f'<w:document xmlns:w="{w}"><w:body>'.encode() + body + b"</w:body></w:document>")


def test_parses_ordinary_documents_like_the_in_process_reader():
    from roletailor.documents import read_docx, read_pdf_text

    docx = make_classic_resume()
    assert sandbox.parse_untrusted(docx, "docx", **LIMITS) == read_docx(docx)
    pdf = helvetica_pdf()
    assert sandbox.parse_untrusted(pdf, "pdf", **LIMITS) == read_pdf_text(pdf)


def test_rejects_a_docx_that_inflates_past_the_part_cap():
    bomb = _bomb(400_000)  # about 28 MB of XML in a file of a few hundred KB
    assert len(bomb) < 1_000_000
    with pytest.raises(sandbox.InvalidDocument):
        sandbox.parse_untrusted(bomb, "docx", **LIMITS)


def test_rejects_too_many_paragraphs_with_a_user_facing_reason():
    with pytest.raises(sandbox.DocumentRejected, match="too many paragraphs"):
        sandbox.parse_untrusted(_bomb(5_000), "docx", **LIMITS)


def test_rejects_pdfs_over_the_page_limit():
    with pytest.raises(sandbox.DocumentRejected, match="at most 0 pages"):
        sandbox.parse_untrusted(helvetica_pdf(), "pdf", **{**LIMITS, "max_pages": 0})


def test_memory_and_time_limits_stop_the_child():
    docx = make_classic_resume()
    with pytest.raises(sandbox.ParseFailed):
        sandbox.parse_untrusted(docx, "docx", **{**LIMITS, "memory_mb": 16})
    with pytest.raises(sandbox.ParseFailed, match="timed out"):
        sandbox.parse_untrusted(docx, "docx", **{**LIMITS, "timeout": 0.01})


def test_child_environment_carries_no_secrets(monkeypatch):
    monkeypatch.setenv("RT_SECRET_KEY", "super-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    captured = {}
    real = sandbox.subprocess.Popen

    def spy(*args, **kwargs):
        captured.update(kwargs["env"])
        return real(*args, **kwargs)

    monkeypatch.setattr(sandbox.subprocess, "Popen", spy)
    sandbox.parse_untrusted(make_classic_resume(), "docx", **LIMITS)
    assert "RT_SECRET_KEY" not in captured and "ANTHROPIC_API_KEY" not in captured


# --- OCR in the sandbox ------------------------------------------------------------------

needs_ocr = pytest.mark.skipif(
    not ocr_available() or soffice_path() is None, reason="tesseract or LibreOffice not installed")
# The production OCR limits (config.py defaults), so a limit that is too tight for real work shows up.
OCR_LIMITS = {"timeout": 150, "memory_mb": 768, "cpu_seconds": 150, "max_pages": 20, "max_blocks": 3000,
              "ocr": True, "ocr_max_pages": 6, "ocr_deadline": 120.0}


def _codes(doc):
    return [f["code"] for f in doc.findings]


@needs_ocr
@pytest.mark.parametrize("pages", [1, 3])
def test_ocr_in_the_sandbox_reads_scans_with_production_limits(pages):
    doc = sandbox.parse_untrusted(scanned_pdf(pages), "pdf", **OCR_LIMITS)
    assert doc.blocks and "ocr_applied" in _codes(doc)
    assert doc.layout_metadata["ocr"] is True and doc.layout_metadata["page_count"] == pages
    assert doc.layout_metadata["ocr_mean_confidence"] > 80
    assert "ocr_outcome" not in doc.layout_metadata
    assert doc.blocks[0].text == "Priya Raman"


@needs_ocr
def test_ocr_off_leaves_a_scan_unread_and_fast():
    import time

    start = time.perf_counter()
    doc = sandbox.parse_untrusted(scanned_pdf(3), "pdf", **{**OCR_LIMITS, "ocr": False})
    assert doc.blocks == [] and _codes(doc) == ["scanned_pdf_needs_ocr"]
    assert "ocr_outcome" not in doc.layout_metadata  # OCR was not tried
    assert time.perf_counter() - start < 10


@needs_ocr
def test_ocr_is_off_by_default():
    doc = sandbox.parse_untrusted(scanned_pdf(1), "pdf", **{k: v for k, v in LIMITS.items()})
    assert doc.blocks == [] and "ocr_outcome" not in doc.layout_metadata


@needs_ocr
def test_ocr_failure_signals_are_distinct():
    blank = sandbox.parse_untrusted(blank_scanned_pdf(1), "pdf", **OCR_LIMITS)
    assert blank.blocks == [] and blank.layout_metadata["ocr_outcome"] == "no_text"
    assert _codes(blank) == ["scanned_pdf_needs_ocr"]

    too_long = sandbox.parse_untrusted(scanned_pdf(3), "pdf", **{**OCR_LIMITS, "ocr_max_pages": 2})
    assert too_long.blocks == [] and too_long.layout_metadata["ocr_outcome"] == "failed"

    slow = sandbox.parse_untrusted(scanned_pdf(1), "pdf", **{**OCR_LIMITS, "ocr_deadline": 0.0})
    assert slow.blocks == [] and slow.layout_metadata["ocr_outcome"] == "timeout"


@needs_ocr
def test_parent_timeout_is_a_parse_timeout():
    with pytest.raises(sandbox.ParseTimeout):
        sandbox.parse_untrusted(scanned_pdf(1), "pdf", **{**OCR_LIMITS, "timeout": 0.05})


def test_child_argv_is_strict():
    assert sandbox.main(["pdf", "768", "60", "20", "3000"]) == sandbox.EXIT_USAGE
    assert sandbox.main(["xlsx", "768", "60", "20", "3000", "0", "6", "45"]) == sandbox.EXIT_USAGE
    assert sandbox.main(["pdf", "768", "60", "20", "3000", "2", "6", "45"]) == sandbox.EXIT_USAGE
    assert sandbox.main(["pdf", "x", "60", "20", "3000", "0", "6", "45"]) == sandbox.EXIT_USAGE
