from __future__ import annotations

from io import BytesIO

import pdfplumber
import pytest
from pypdf import PdfReader, PdfWriter

from roletailor.documents import (
    EditRejected,
    PdfInPlaceUnsupported,
    docx_to_pdf,
    edit_pdf_in_place,
    pages_without_text,
    read_pdf_text,
)
from roletailor.documents.pdf import soffice_path
from roletailor.documents.pdf_layout import pdf_paragraphs
from tests.fixtures import make_classic_resume

from .pdf_helpers import (
    block_boxes,
    font_file,
    form_xobject_pdf,
    helvetica_pdf,
    pixel_diff,
    ttf_embedded_pdf,
    two_page_pdf,
)

MAX_OUTSIDE_FRACTION = 0.0005  # anti-aliasing slack: 0.05% of the page

SUMMARY = "l3"
FIRST_BULLET = "l6"
SECOND_BULLET = "l7"
TITLE_LINE = "l5"


@pytest.fixture(scope="module")
def classic() -> bytes:
    if soffice_path() is None:
        pytest.skip("LibreOffice not installed")
    return docx_to_pdf(make_classic_resume())


def texts(data: bytes) -> dict[str, str]:
    return {p.id: p.text for p in pdf_paragraphs(data)}


def plumber_text(data: bytes) -> str:
    with pdfplumber.open(BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def pypdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(data)).pages)


def assert_only_changed(before: bytes, after: bytes, edited: dict[str, str]) -> None:
    old, new = texts(before), texts(after)
    assert old.keys() == new.keys()
    for block_id, text in old.items():
        assert new[block_id] == edited.get(block_id, text)


# --- reader contract ---------------------------------------------------------------------------


def test_pages_without_text(classic):
    assert pages_without_text(classic) == []
    assert pages_without_text(two_page_pdf()) == []
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    out = BytesIO()
    writer.write(out)
    assert pages_without_text(out.getvalue()) == [0]
    assert not read_pdf_text(out.getvalue()).supports_in_place_edit


def test_fragments_split_title_and_date(classic):
    line = {p.id: p for p in pdf_paragraphs(classic)}[TITLE_LINE].lines[0]
    assert [f.text for f in line.fragments] == ["Northwind Analytics — Senior Data Engineer", "Mar 2021 – Present"]
    assert line.fragments[1].x1 > 500


# --- classic LibreOffice resume ----------------------------------------------------------------


def test_visual_diff_only_edited_blocks_change(classic):
    edits = {
        SUMMARY: "Data engineer who ships reliable streaming and batch pipelines from prototype to production.",
        SECOND_BULLET: "Cut nightly batch runtime from 6.5 to 1.1 hours by tuning Delta partitioning.",
    }
    out, report = edit_pdf_in_place(classic, edits)
    assert_only_changed(classic, out, edits)
    boxes = block_boxes(classic, edits) + block_boxes(out, edits)
    outside, inside = pixel_diff(classic, out, boxes)
    assert outside <= MAX_OUTSIDE_FRACTION
    assert inside > 0
    assert {b.block_id for b in report.blocks} == set(edits)


def test_wrapped_summary_reflows_into_same_slots(classic):
    old = texts(classic)[SUMMARY]
    longer = old.replace("production.", "production, including real-time fraud detection at scale.")
    out, report = edit_pdf_in_place(classic, {SUMMARY: longer})
    entry = report.by_id()[SUMMARY]
    assert (entry.lines_before, entry.lines_after) == (2, 2)
    assert texts(out)[SUMMARY] == longer
    shorter, _ = edit_pdf_in_place(classic, {SUMMARY: "Data engineer."})
    assert texts(shorter)[SUMMARY] == "Data engineer."


def test_single_bullet_edit_keeps_bullet_glyph(classic):
    out, _ = edit_pdf_in_place(classic, {SECOND_BULLET: "Cut batch runtime by 70%."})
    before = {p.id: p for p in pdf_paragraphs(classic)}[SECOND_BULLET]
    after = {p.id: p for p in pdf_paragraphs(out)}[SECOND_BULLET]
    assert after.is_list_item and after.bullet == before.bullet
    assert after.text == "Cut batch runtime by 70%."
    assert after.lines[0].bullet_x0 == pytest.approx(before.lines[0].bullet_x0)
    assert after.lines[0].x0 == pytest.approx(before.lines[0].x0)


def test_glyph_missing_from_subset_uses_substitute_font(classic):
    text = "Quarterbacked jazzy workflows with Xylophone-grade QA"
    out, report = edit_pdf_in_place(classic, {SECOND_BULLET: text})
    assert report.by_id()[SECOND_BULLET].method == "substitute_font"
    assert texts(out)[SECOND_BULLET] == text
    assert b"Carlito" in out
    boxes = block_boxes(classic, [SECOND_BULLET]) + block_boxes(out, [SECOND_BULLET])
    outside, inside = pixel_diff(classic, out, boxes)
    assert outside <= MAX_OUTSIDE_FRACTION and inside > 0


def test_reuse_font_when_glyphs_available(classic):
    _, report = edit_pdf_in_place(classic, {SECOND_BULLET: "Cut nightly batch runtime."})
    assert report.by_id()[SECOND_BULLET].method == "reuse_font"
    assert report.by_id()[SECOND_BULLET].font_scale == 1.0


def test_overflow_beyond_shrink_is_unsupported(classic):
    with pytest.raises(PdfInPlaceUnsupported) as info:
        edit_pdf_in_place(classic, {SECOND_BULLET: "Cut nightly batch runtime " * 12})
    assert info.value.block_id == SECOND_BULLET


def test_slightly_long_text_shrinks_font(classic):
    old = texts(classic)[SECOND_BULLET]
    out, report = edit_pdf_in_place(classic, {SECOND_BULLET: old + " More."})
    entry = report.by_id()[SECOND_BULLET]
    assert 0.9 <= entry.font_scale < 1.0
    assert texts(out)[SECOND_BULLET].endswith("More.")


def test_date_fragment_edit_keeps_right_edge(classic):
    new = "Mar 2021 – Jan 2026"
    out, report = edit_pdf_in_place(classic, {TITLE_LINE: f"Northwind Analytics — Senior Data Engineer {new}"})
    assert report.by_id()[TITLE_LINE].fragment_only
    old_line = {p.id: p for p in pdf_paragraphs(classic)}[TITLE_LINE].lines[0]
    new_line = {p.id: p for p in pdf_paragraphs(out)}[TITLE_LINE].lines[0]
    assert [f.text for f in new_line.fragments] == [old_line.fragments[0].text, new]
    assert new_line.fragments[1].x1 == pytest.approx(old_line.fragments[1].x1, abs=0.6)
    assert new_line.fragments[0].x0 == pytest.approx(old_line.fragments[0].x0)
    outside, inside = pixel_diff(classic, out, block_boxes(classic, [TITLE_LINE]) + block_boxes(out, [TITLE_LINE]))
    assert outside <= MAX_OUTSIDE_FRACTION and inside > 0


def test_title_run_edit_leaves_bold_company_untouched(classic):
    out, _ = edit_pdf_in_place(classic, {TITLE_LINE: "Northwind Analytics — Staff Data Engineer Mar 2021 – Present"})
    assert texts(out)[TITLE_LINE] == "Northwind Analytics — Staff Data Engineer Mar 2021 – Present"


def test_edit_spanning_two_fragments_is_unsupported(classic):
    with pytest.raises(PdfInPlaceUnsupported):
        edit_pdf_in_place(classic, {TITLE_LINE: "Northwind Analytics — Staff Data Engineer Mar 2022 – Present"})


def test_edit_touching_the_bold_label_is_unsupported(classic):
    with pytest.raises(PdfInPlaceUnsupported):
        edit_pdf_in_place(classic, {TITLE_LINE: "Northwind Labs — Senior Data Engineer Mar 2021 – Present"})


def test_old_text_is_gone_for_every_extractor_and_order_is_kept(classic):
    out, _ = edit_pdf_in_place(classic, {SECOND_BULLET: "Cut batch runtime by 70% with dbt."})
    old = "repartitioning Delta tables"
    for extract in (plumber_text, pypdf_text):
        text = extract(out)
        assert old not in text
        assert "Cut batch runtime by 70% with dbt." in text
        # in place: still between the bullets around it, not appended at the end of the page
        assert text.index("Designed a streaming") < text.index("Cut batch runtime") < text.index("Led migration")


def test_centred_name_stays_centred(classic):
    out, _ = edit_pdf_in_place(classic, {"l0": "Priya Raman-Iyer"})
    line = {p.id: p for p in pdf_paragraphs(out)}["l0"].lines[0]
    assert (line.x0 + line.x1) / 2 == pytest.approx(306, abs=1.0)


def test_non_ascii_text(classic):
    text = "Led café-scale migration – résumé of 120 DAGs."
    out, _ = edit_pdf_in_place(classic, {"l8": text})
    assert texts(out)["l8"] == text
    assert text in pypdf_text(out)


def test_unknown_block_id_raises_edit_rejected(classic):
    with pytest.raises(EditRejected):
        edit_pdf_in_place(classic, {"l999": "x"})


def test_noop_edits_return_identical_bytes(classic):
    assert edit_pdf_in_place(classic, {})[0] is classic
    same = {SUMMARY: texts(classic)[SUMMARY], SECOND_BULLET: texts(classic)[SECOND_BULLET] + "  "}
    out, report = edit_pdf_in_place(classic, same)
    assert out == classic and report.blocks == ()


def test_output_is_deterministic(classic):
    edits = {SUMMARY: "Data engineer shipping pipelines.", SECOND_BULLET: "Quartz jazz."}
    assert edit_pdf_in_place(classic, edits)[0] == edit_pdf_in_place(classic, edits)[0]


def test_empty_edit_is_unsupported(classic):
    with pytest.raises(PdfInPlaceUnsupported):
        edit_pdf_in_place(classic, {SECOND_BULLET: "  "})


def test_failure_changes_nothing_for_other_edits(classic):
    with pytest.raises(PdfInPlaceUnsupported):
        edit_pdf_in_place(classic, {SUMMARY: "Fine edit.", SECOND_BULLET: "word " * 200})


# --- small generated PDFs ----------------------------------------------------------------------


def test_helvetica_non_embedded_reuses_standard_font():
    data = helvetica_pdf()
    out, report = edit_pdf_in_place(data, {"l1": "Platform engineer: café – résumé."})
    assert report.by_id()["l1"].method == "reuse_font"
    assert texts(out)["l1"] == "Platform engineer: café – résumé."
    outside, inside = pixel_diff(data, out, block_boxes(data, ["l1"]) + block_boxes(out, ["l1"]))
    assert outside <= MAX_OUTSIDE_FRACTION and inside > 0


def test_bullet_in_same_show_operator_is_redrawn():
    data = helvetica_pdf()
    out, _ = edit_pdf_in_place(data, {"l2": "Cut p99 latency by 55% on checkout."})
    par = {p.id: p for p in pdf_paragraphs(out)}["l2"]
    assert par.is_list_item and par.bullet == "-" and par.text == "Cut p99 latency by 55% on checkout."
    assert "Reduced latency" not in pypdf_text(out)


def test_right_aligned_date_in_helvetica_stays_right_aligned():
    data = helvetica_pdf()
    out, report = edit_pdf_in_place(data, {"l4": "Acme Corp - Senior Engineer 2020 - Present, remote"})
    assert report.by_id()["l4"].fragment_only
    line = {p.id: p for p in pdf_paragraphs(out)}["l4"].lines[0]
    assert line.fragments[-1].x1 == pytest.approx(540, abs=0.6)
    assert line.fragments[-1].text == "2020 - Present, remote"


def test_two_page_edit_on_second_page_leaves_first_untouched():
    data = two_page_pdf()
    out, _ = edit_pdf_in_place(data, {"l2": "Second page closing line, edited."})
    assert_only_changed(data, out, {"l2": "Second page closing line, edited."})
    assert pixel_diff(data, out, [], page=0) == (0.0, 0)
    outside, inside = pixel_diff(data, out, block_boxes(data, ["l2"]) + block_boxes(out, ["l2"]), page=1)
    assert outside <= MAX_OUTSIDE_FRACTION and inside > 0


def test_ttf_embedded_font():
    path = font_file("Carlito") or font_file("DejaVu Sans")
    if path is None:
        pytest.skip("no TrueType font available")
    data = ttf_embedded_pdf(path)
    out, report = edit_pdf_in_place(data, {"l1": "Built a Quartz-based developer portal."})
    assert texts(out)["l1"] == "Built a Quartz-based developer portal."
    assert report.by_id()["l1"].method in ("reuse_font", "substitute_font")
    outside, inside = pixel_diff(data, out, block_boxes(data, ["l1"]) + block_boxes(out, ["l1"]))
    assert outside <= MAX_OUTSIDE_FRACTION and inside > 0


def test_text_inside_form_xobject_is_unsupported():
    data = form_xobject_pdf()
    assert [p.text for p in pdf_paragraphs(data)] == ["Visible on the page.", "Hidden inside a form."]
    with pytest.raises(PdfInPlaceUnsupported):
        edit_pdf_in_place(data, {"l1": "Changed form text."})
    out, _ = edit_pdf_in_place(data, {"l0": "Changed page text."})
    assert texts(out)["l1"] == "Hidden inside a form."
