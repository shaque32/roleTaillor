from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from pypdf import PdfWriter

from roletailor.documents import (
    InvalidDocument,
    PdfConversionError,
    apply_block_edits,
    count_pdf_pages,
    docx_to_pdf,
    read_pdf_text,
)
from roletailor.documents.pdf import soffice_path
from tests.fixtures import make_classic_resume

needs_soffice = pytest.mark.skipif(soffice_path() is None, reason="LibreOffice not installed")


@pytest.fixture(scope="module")
def classic_pdf() -> bytes:
    if soffice_path() is None:
        pytest.skip("LibreOffice not installed")
    return docx_to_pdf(make_classic_resume())


@needs_soffice
def test_conversion_produces_one_page(classic_pdf):
    assert classic_pdf.startswith(b"%PDF")
    assert count_pdf_pages(classic_pdf) == 1


@needs_soffice
def test_edited_docx_converts():
    edited = apply_block_edits(make_classic_resume(), {"p3": "Tailored summary for the role."})
    assert "Tailored summary" in read_pdf_text(docx_to_pdf(edited)).blocks[3].text


@needs_soffice
def test_read_pdf_text_structure(classic_pdf):
    doc = read_pdf_text(classic_pdf)
    assert doc.source_format == "pdf" and doc.supports_in_place_edit
    assert [b.id for b in doc.blocks] == [f"l{n}" for n in range(len(doc.blocks))]
    assert all(b.kind == "text_line" for b in doc.blocks)
    assert doc.blocks[0].text == "Priya Raman" and not doc.blocks[0].is_heading
    headings = [b.text for b in doc.blocks if b.is_heading]
    assert headings == ["SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION", "CERTIFICATIONS"]
    summary = doc.blocks[3]
    assert summary.text.startswith("Data and machine learning") and summary.text.endswith(
        "production.")  # wrapped lines merged into one block
    bullets = [b for b in doc.blocks if b.is_list_item]
    assert len(bullets) == 11
    assert bullets[0].text.startswith("Designed a streaming")  # glyph stripped
    assert doc.findings == []
    assert doc.layout_metadata["page_count"] == 1
    assert doc.layout_metadata["page_width_in"] == 8.5


def test_blank_pdf_needs_ocr():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    out = BytesIO()
    writer.write(out)
    doc = read_pdf_text(out.getvalue())
    assert doc.blocks == []
    assert [f["code"] for f in doc.findings] == ["scanned_pdf_needs_ocr"]
    assert count_pdf_pages(out.getvalue()) == 1


def test_invalid_pdf_raises():
    with pytest.raises(InvalidDocument):
        count_pdf_pages(b"not a pdf")


def test_missing_soffice_raises(monkeypatch):
    monkeypatch.setenv("RT_SOFFICE", "/nonexistent/soffice")
    with pytest.raises(PdfConversionError):
        docx_to_pdf(make_classic_resume())


@needs_soffice
def test_concurrent_conversions_do_not_collide():
    data = make_classic_resume()
    with ThreadPoolExecutor(max_workers=3) as pool:
        pdfs = list(pool.map(docx_to_pdf, [data] * 3))
    assert all(count_pdf_pages(pdf) == 1 for pdf in pdfs)
