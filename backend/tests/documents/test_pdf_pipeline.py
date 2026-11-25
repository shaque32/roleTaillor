"""PDF sources end to end below the database: layout fit, rendering modes, second generator."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from roletailor.documents import (
    count_pdf_pages,
    edit_pdf_in_place,
    fit_pdf_edits,
    read_pdf_text,
)
from roletailor.pipeline.orchestrator import _fit_pdf_layout
from roletailor.services import rendering
from roletailor.storage import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE

# A resume printed to PDF by Chromium (Skia): one large text object, subset TrueType fonts.
CHROME_PDF = (Path(__file__).parent.parent / "fixtures" / "pdf" / "chrome_resume.pdf").read_bytes()

SUMMARY = (
    "Platform and MLOps engineer with 9 years of experience designing data infrastructure, model "
    "governance and observability for regulated fintech products, focused on reliability and cost."
)
FITS = {"l3": SUMMARY, "l6": "Built a feature store on Postgres and Redis serving 120 models at p99 under 25 ms."}
TOO_LONG = {"l10": "Python, Go, Kubernetes, Terraform, Airflow, Spark, MLflow, " + ", ".join(["Kafka"] * 30)}


def _base(pdf: bytes | None) -> rendering.Base:
    document = read_pdf_text(CHROME_PDF)
    return rendering.Base(version={"content": {}}, document=document, docx=None, pdf=pdf)


def _text(pdf: bytes) -> str:
    return " ".join("".join(p.extract_text() or "" for p in PdfReader(BytesIO(pdf)).pages).split())


def test_chrome_pdf_reads_and_edits_in_place():
    document = read_pdf_text(CHROME_PDF)
    assert document.supports_in_place_edit
    assert [b.text for b in document.blocks if b.is_heading] == ["SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION"]
    edited, report = edit_pdf_in_place(CHROME_PDF, FITS)
    assert {b.block_id for b in report.blocks} == set(FITS)
    after = read_pdf_text(edited)
    assert [b.id for b in after.blocks] == [b.id for b in document.blocks]
    assert after.block("l3").text == SUMMARY
    text = _text(edited)
    assert "MLOps engineer" in text and "under 30 ms" not in text
    # Reading order is preserved for parsers that follow the content stream.
    assert text.index("SUMMARY") < text.index("MLOps engineer") < text.index("EXPERIENCE")
    assert count_pdf_pages(edited) == 1


def test_fit_drops_only_edits_that_cannot_keep_the_layout():
    kept, dropped = fit_pdf_edits(CHROME_PDF, {**FITS, **TOO_LONG})
    assert kept == FITS and list(dropped) == ["l10"]
    assert "fit" in dropped["l10"]
    edit_pdf_in_place(CHROME_PDF, kept)  # guaranteed to succeed


def test_pipeline_reverts_a_minority_of_edits_to_keep_the_layout():
    edits, outcome = _fit_pdf_layout(CHROME_PDF, {**FITS, **TOO_LONG})
    assert edits == FITS
    assert outcome.rule_key == "layout.pdf_in_place" and outcome.details["mode"] == "in_place"
    assert list(outcome.details["reverted"]) == ["l10"]


def test_pipeline_keeps_content_when_most_edits_would_be_lost():
    edits, outcome = _fit_pdf_layout(CHROME_PDF, TOO_LONG)
    assert edits == TOO_LONG and outcome.details["mode"] == "template"
    # Nothing was reverted, so the score stays at 100; the misfits explain the template.
    assert outcome.details["reverted"] == {} and outcome.score == 100.0
    assert list(outcome.details["unfit"]) == ["l10"]


def test_render_primary_keeps_pdf_layout():
    out = rendering.render_primary(_base(CHROME_PDF), FITS, None)
    assert out.mode == "pdf_in_place" and out.media_type == PDF_MEDIA_TYPE and out.extension == ".pdf"
    blocks = rendering.edited_blocks(read_pdf_text(CHROME_PDF), FITS)
    assert rendering.pdf_addresses_blocks(out.data, blocks)
    assert rendering.render_pdf(_base(CHROME_PDF), FITS, None) == out.data


def test_render_primary_falls_back_to_template_with_reason():
    out = rendering.render_primary(_base(CHROME_PDF), TOO_LONG, None)
    assert out.mode == "template" and out.media_type == DOCX_MEDIA_TYPE
    assert out.fallback_reason and "l10" in out.fallback_reason
    assert out.data.startswith(b"PK")


def test_pdf_without_in_place_support_uses_template():
    out = rendering.render_primary(_base(None), FITS, None)
    assert out.mode == "template" and out.fallback_reason is None


@pytest.mark.parametrize("data", [b"not a pdf", b""])
def test_pdf_addresses_blocks_rejects_unreadable(data):
    assert not rendering.pdf_addresses_blocks(data, [])


def test_ocr_source_reports_why_the_template_is_used():
    document = read_pdf_text(CHROME_PDF).model_copy(update={"layout_metadata": {"ocr": True}})
    base = rendering.Base(version={"content": {}}, document=document, docx=None, pdf=None)
    out = rendering.render_primary(base, FITS, None)
    assert out.mode == "template" and "OCR" in out.fallback_reason
