"""The sandboxed parser: real child processes, real limits."""

from __future__ import annotations

import io
import zipfile

import pytest

from roletailor.documents import sandbox
from tests.fixtures import make_classic_resume

from .pdf_helpers import helvetica_pdf

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
