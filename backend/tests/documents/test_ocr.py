from __future__ import annotations

import time
from io import BytesIO

import pytest
from pypdf import PdfReader

from roletailor.documents import docx_to_pdf
from roletailor.documents.errors import InvalidDocument, OcrError
from roletailor.documents.ocr import (
    OcrPage,
    ocr_available,
    ocr_findings,
    ocr_pdf_pages,
    parse_tsv,
)
from roletailor.documents.pdf import soffice_path
from tests.fixtures import make_classic_resume

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"


def _row(block: int, par: int, line: int, word: int, conf: float, text: str) -> str:
    return f"5\t1\t{block}\t{par}\t{line}\t{word}\t0\t0\t10\t10\t{conf}\t{text}"


def _tsv(*rows: str) -> str:
    structural = "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t"
    return "\n".join([HEADER, structural, *rows]) + "\n"


def test_parse_groups_words_into_lines_with_paragraph_breaks():
    tsv = _tsv(
        _row(1, 1, 1, 1, 96, "Priya"), _row(1, 1, 1, 2, 90, "Raman"),
        _row(2, 1, 1, 1, 80, "SUMMARY"),
        _row(2, 2, 1, 1, 70, "Built"), _row(2, 2, 1, 2, 70, "things"),
        _row(2, 2, 2, 1, 60, "quickly"),
    )
    lines, mean = parse_tsv(tsv)
    assert lines == ["Priya Raman", "", "SUMMARY", "", "Built things", "quickly"]
    assert mean == round((96 + 90 + 80 + 70 + 70 + 60) / 6, 1)


def test_parse_ignores_structural_and_empty_rows():
    tsv = _tsv(_row(1, 1, 1, 1, 90, "Hello"), _row(1, 1, 1, 2, 10, "   "), _row(1, 1, 1, 3, -1, "ghost"))
    assert parse_tsv(tsv) == (["Hello"], 90.0)
    assert parse_tsv(_tsv()) == ([], 0.0)


def test_unambiguous_bullet_glyphs_normalised():
    tsv = _tsv(_row(1, 1, 1, 1, 90, "°"), _row(1, 1, 1, 2, 90, "Led"),
               _row(1, 1, 2, 1, 90, "«"), _row(1, 1, 2, 2, 90, "Built"))
    assert parse_tsv(tsv)[0] == ["• Led", "• Built"]


def test_letter_bullets_need_a_run_of_two():
    def para(*texts: str) -> str:
        return _tsv(*[_row(1, 1, n, 1, 90, t) for n, t in enumerate(texts, 1)])

    assert parse_tsv(para("e Led a team", "o Shipped it", "Plain line"))[0] == [
        "• Led a team", "• Shipped it", "Plain line"]
    assert parse_tsv(para("o Led a team", "Plain line"))[0] == ["o Led a team", "Plain line"]


def test_findings():
    good = [OcrPage(0, ["a b c"], 90.0)]
    assert [f["code"] for f in ocr_findings(good)] == ["ocr_applied"]
    assert "1 scanned page(s); mean confidence 90%" in ocr_findings(good)[0]["detail"]
    bad = [OcrPage(0, ["a b c"], 50.0)]
    assert [f["code"] for f in ocr_findings(bad)] == ["ocr_applied", "ocr_low_confidence"]


needs_ocr = pytest.mark.skipif(
    not ocr_available() or soffice_path() is None, reason="tesseract or LibreOffice not installed")


@pytest.fixture(scope="module")
def scanned_pdf() -> bytes:
    """Image-only PDF: the classic resume rasterised at 200 dpi, with no text layer."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(docx_to_pdf(make_classic_resume()))
    image = pdf[0].render(scale=200 / 72, grayscale=True).to_pil().convert("RGB")
    out = BytesIO()
    image.save(out, format="PDF", resolution=200)
    return out.getvalue()


@needs_ocr
def test_scanned_fixture_has_no_text_layer(scanned_pdf):
    assert "".join(p.extract_text() or "" for p in PdfReader(BytesIO(scanned_pdf)).pages).strip() == ""


@needs_ocr
def test_ocr_reads_scanned_resume(scanned_pdf):
    start = time.perf_counter()
    pages = ocr_pdf_pages(scanned_pdf)
    elapsed = time.perf_counter() - start
    print(f"\nOCR wall time for 1 page: {elapsed:.2f}s")
    assert len(pages) == 1 and pages[0].index == 0
    lines = pages[0].lines
    assert any("Priya Raman" in line for line in lines)
    for heading in ("SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION"):
        assert heading in lines
    assert pages[0].mean_confidence > 80


@needs_ocr
def test_ocr_output_feeds_the_pdf_line_merger(scanned_pdf):
    from roletailor.documents.pdf import merge_text_lines

    paragraphs = merge_text_lines(ocr_pdf_pages(scanned_pdf)[0].lines)
    assert any(is_list for _, is_list in paragraphs)


@needs_ocr
def test_scanned_upload_is_read_with_ocr_and_uses_the_template(scanned_pdf):
    from roletailor.documents import read_pdf_text

    doc = read_pdf_text(scanned_pdf)
    assert not doc.supports_in_place_edit and doc.layout_metadata["ocr"] is True
    codes = [f["code"] for f in doc.findings]
    assert "ocr_applied" in codes and "scanned_pdf_needs_ocr" not in codes
    assert doc.blocks[0].text == "Priya Raman"
    headings = [b.text for b in doc.blocks if b.is_heading]
    assert {"SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION"} <= set(headings)
    assert sum(b.is_list_item for b in doc.blocks) >= 8


def test_scanned_upload_without_tesseract_keeps_the_needs_ocr_finding(monkeypatch):
    from io import BytesIO

    from pypdf import PdfWriter

    from roletailor.documents import ocr, read_pdf_text

    monkeypatch.setattr(ocr, "ocr_available", lambda: False)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    out = BytesIO()
    writer.write(out)
    doc = read_pdf_text(out.getvalue())
    assert doc.blocks == [] and [f["code"] for f in doc.findings] == ["scanned_pdf_needs_ocr"]


@needs_ocr
def test_page_selection(scanned_pdf):
    assert ocr_pdf_pages(scanned_pdf, [0])[0].index == 0
    with pytest.raises(OcrError):
        ocr_pdf_pages(scanned_pdf, [5])


def test_missing_binary_raises(monkeypatch):
    monkeypatch.setenv("RT_TESSERACT", "/nonexistent/tesseract")
    with pytest.raises(OcrError):
        ocr_pdf_pages(b"%PDF-1.4")


@needs_ocr
def test_too_many_pages_raises(scanned_pdf):
    with pytest.raises(OcrError, match="limit 1"):
        ocr_pdf_pages(scanned_pdf, [0, 0], max_pages=1)


@needs_ocr
def test_non_pdf_bytes_raise_invalid_document():
    """Garbage input is a bad upload (InvalidDocument), not an OCR infrastructure failure."""
    with pytest.raises(InvalidDocument):
        ocr_pdf_pages(b"definitely not a pdf")
