from __future__ import annotations

from io import BytesIO

import pdfplumber
import pikepdf
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
from roletailor.documents import pdf_writer as writer
from roletailor.documents.pdf import soffice_path
from roletailor.documents.pdf_content import _font as content_font
from roletailor.documents.pdf_content import walk
from roletailor.documents.pdf_fonts import load_pdf_font
from roletailor.documents.pdf_layout import pdf_paragraphs
from tests.fixtures import make_classic_resume

from .pdf_helpers import (
    LEFT_BULLETS,
    RIGHT_BULLETS,
    block_boxes,
    font_dictionary,
    font_file,
    form_xobject_pdf,
    helvetica_pdf,
    one_text_object_pdf,
    pixel_diff,
    raw_pdf,
    title_date_rows_pdf,
    ttf_embedded_pdf,
    two_column_pdf,
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


# --- review regressions ------------------------------------------------------------------------


def lines_of(data: bytes) -> dict[str, object]:
    return {p.id: p for p in pdf_paragraphs(data)}


def test_two_columns_are_read_per_column_with_each_bullet_a_block():
    data = two_column_pdf()
    pars = pdf_paragraphs(data)
    assert [p.text for p in pars] == ["EXPERIENCE", *LEFT_BULLETS, *RIGHT_BULLETS, "Languages: English, Hindi"]
    assert all(p.is_list_item for p in pars[1:13])
    left, right = pars[1], pars[7]
    assert left.lines[0].limit_left is None and left.lines[0].limit_right == pytest.approx(288, abs=0.5)
    assert right.lines[0].limit_left == pytest.approx(330, abs=0.5) and right.lines[0].limit_right is None
    assert pars[0].lines[0].limit_right is None and pars[-1].lines[0].limit_right is None


def test_left_column_edit_stays_inside_its_column():
    data = two_column_pdf()
    new = "Cut nightly batch runtime by 70 percent in Q3."
    out, _ = edit_pdf_in_place(data, {"l1": new})
    assert_only_changed(data, out, {"l1": new})
    line = lines_of(out)["l1"].lines[0]
    assert line.x1 <= lines_of(data)["l1"].lines[0].limit_right + 0.5
    outside, inside = pixel_diff(data, out, block_boxes(data, ["l1"]) + block_boxes(out, ["l1"]))
    assert outside <= MAX_OUTSIDE_FRACTION and inside > 0
    assert "Shipped a payments ledger, exactly-once." in pypdf_text(out)


def test_left_column_text_never_reflows_into_the_gutter():
    # 330 pt wide: it fits the page's right margin, but not the left column.
    too_wide = "Cut nightly batch runtime by 70 percent across every production pipeline."
    with pytest.raises(PdfInPlaceUnsupported):
        edit_pdf_in_place(two_column_pdf(), {"l1": too_wide})


def test_right_column_edit_leaves_left_column_untouched():
    data = two_column_pdf()
    out, _ = edit_pdf_in_place(data, {"l8": "Owned p99 latency and error budgets."})
    assert_only_changed(data, out, {"l8": "Owned p99 latency and error budgets."})
    outside, inside = pixel_diff(data, out, block_boxes(data, ["l8"]) + block_boxes(out, ["l8"]))
    assert outside <= MAX_OUTSIDE_FRACTION and inside > 0


def test_title_rows_with_right_aligned_dates_are_not_columns():
    data = title_date_rows_pdf()
    pars = pdf_paragraphs(data)
    assert len(pars) == 5
    for par in pars:
        (line,) = par.lines
        assert len(line.fragments) == 2 and line.limit_left is None and line.limit_right is None
        assert line.fragments[1].text == "2020 - 2023"


def test_edit_in_one_text_object_keeps_stream_order_and_position():
    data = one_text_object_pdf()
    new = "First paragraph, rewritten."
    out, _ = edit_pdf_in_place(data, {"l0": new})
    assert_only_changed(data, out, {"l0": new})
    order = [pypdf_text(out).index(t) for t in (new, "Second paragraph", "Third paragraph", "Fourth paragraph",
                                                  "Fifth paragraph")]
    assert order == sorted(order)
    outside, inside = pixel_diff(data, out, block_boxes(data, ["l0"]) + block_boxes(out, ["l0"]))
    assert outside <= MAX_OUTSIDE_FRACTION and inside > 0
    for block_id in ("l2", "l3"):  # relative moves after the split still land where they did
        old_line, new_line = lines_of(data)[block_id].lines[0], lines_of(out)[block_id].lines[0]
        assert new_line.baseline == pytest.approx(old_line.baseline, abs=0.01)


def test_edit_in_middle_of_text_object_and_mid_line_split():
    data = one_text_object_pdf()
    out, _ = edit_pdf_in_place(data, {"l1": "Second paragraph, reworded.", "l3": "Fourth paragraph, reworded."})
    assert [p.text for p in pdf_paragraphs(out)][1] == "Second paragraph, reworded."
    text = pypdf_text(out)
    assert text.index("Second paragraph, reworded.") < text.index("Third") < text.index("Fourth paragraph, reworded.")
    assert text.index("Fourth paragraph, reworded.") < text.index("Fifth")
    outside, _ = pixel_diff(data, out, block_boxes(data, ["l1", "l3"]) + block_boxes(out, ["l1", "l3"]))
    assert outside <= MAX_OUTSIDE_FRACTION

    stream = "BT /F1 10 Tf 72 700 Td (Acme Developer) Tj [-30000] TJ (2020) Tj 0 -40 Td (Closing line stays.) Tj ET"
    mid = raw_pdf(stream)
    before = lines_of(mid)["l0"].lines[0]
    assert [f.text for f in before.fragments] == ["Acme Developer", "2020"]
    out2, _ = edit_pdf_in_place(mid, {"l0": "Acme Senior Developer 2020"})
    after = lines_of(out2)["l0"].lines[0]
    assert [f.text for f in after.fragments] == ["Acme Senior Developer", "2020"]
    assert after.fragments[1].x0 == pytest.approx(before.fragments[1].x0, abs=0.05)
    assert lines_of(out2)["l1"].lines[0].baseline == pytest.approx(660, abs=0.01)
    assert pypdf_text(out2).index("Acme Senior") < pypdf_text(out2).index("2020") < pypdf_text(out2).index("Closing")


def test_open_marked_content_inside_text_object_is_unsupported():
    stream = ("BT /F1 10 Tf 72 700 Td (Edited line here.) Tj /Span BMC 0 -20 Td (Inner marked text.) Tj EMC "
              "0 -20 Td (Last line.) Tj ET")
    data = raw_pdf(stream)
    out, _ = edit_pdf_in_place(data, {"l0": "Edited line, changed."})
    assert "Edited line, changed." in pypdf_text(out)
    open_stream = "BT /F1 10 Tf 72 700 Td /Span BMC (Edited line here.) Tj 0 -20 Td (Later line.) Tj EMC ET"
    with pytest.raises(PdfInPlaceUnsupported):
        edit_pdf_in_place(raw_pdf(open_stream), {"l0": "Edited line, changed."})


def test_text_rise_is_unsupported():
    data = raw_pdf("BT /F1 10 Tf 72 700 Td (Plain line.) Tj 0 -20 Td 4 Ts (Raised line.) Tj 0 Ts ET")
    with pytest.raises(PdfInPlaceUnsupported):
        edit_pdf_in_place(data, {"l1": "Raised line, edited."})
    out, _ = edit_pdf_in_place(data, {"l0": "Plain line, edited."})
    assert "Plain line, edited." in pypdf_text(out)


@pytest.mark.parametrize("mode", [1, 3, 7])
def test_non_fill_render_mode_is_unsupported(mode):
    data = raw_pdf(f"BT /F1 10 Tf 72 700 Td (Normal line.) Tj 0 -20 Td {mode} Tr (Odd line.) Tj 0 Tr ET")
    with pytest.raises(PdfInPlaceUnsupported) as info:
        edit_pdf_in_place(data, {"l1": "Odd line, edited."})
    assert "render mode" in info.value.reason or "locate" in info.value.reason


def test_unencodable_wrap_line_is_rejected_and_unexpected_errors_become_unsupported(monkeypatch):
    class Codec:
        def can_encode(self, text: str) -> bool:
            return "~" not in text

        def width(self, text: str, size: float) -> float:
            return 0.0 if "~" in text else len(text) * size / 2

    assert writer._wrap(Codec(), ["ab", "c~d"], 10, [100]) is None
    assert writer._wrap(Codec(), ["ab", "cd"], 10, [100]) == ["ab cd"]
    assert writer._wrap(Codec(), ["ab", "cd"], 10, [11, 100]) == ["ab", "cd"]
    assert writer._wrap(Codec(), ["ab", "c~d"], 10, [11, 100]) is None

    def boom(*args, **kwargs):
        raise ValueError("cannot encode")

    monkeypatch.setattr(writer, "_plan_block", boom)
    with pytest.raises(PdfInPlaceUnsupported):
        edit_pdf_in_place(helvetica_pdf(), {"l1": "Changed text."})
    with pytest.raises(EditRejected):
        edit_pdf_in_place(helvetica_pdf(), {"l99": "Changed text."})


def _type0(encoding: str) -> dict:
    return {"/Type": "/Font", "/Subtype": "/Type0", "/BaseFont": "/Test", "/Encoding": f"/{encoding}"}


def _load(spec: dict, **extra: object):
    pdf = pikepdf.Pdf.new()
    obj = font_dictionary(spec)
    for key, value in extra.items():
        obj[f"/{key}"] = value
    return load_pdf_font(pdf.make_indirect(obj))


def test_vertical_type0_font_is_not_reusable_and_has_no_horizontal_advance():
    pdf = pikepdf.Pdf.new()
    cmap = pdf.make_stream(b"1 beginbfchar\n<0001> <0041>\nendbfchar")
    descendant = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2,
                                                      DW=1000))
    spec = {**_type0("Identity-V"), "/DescendantFonts": pikepdf.Array([descendant]), "/ToUnicode": cmap}
    font = load_pdf_font(pdf.make_indirect(font_dictionary(spec)))
    assert font.vertical and not font.can_encode("A")
    spec_h = {**spec, "/Encoding": pikepdf.Name("/Identity-H")}
    horizontal = load_pdf_font(pdf.make_indirect(font_dictionary(spec_h)))
    assert not horizontal.vertical and horizontal.can_encode("A")

    resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F2=pdf.make_indirect(font_dictionary(spec))))
    shows = walk(list(pikepdf.parse_content_stream(pdf.make_stream(b"BT /F2 10 Tf <0001> Tj ET"))), resources).shows
    assert shows[0].advance is None


def test_simple_font_encoding_is_taken_from_the_declaration():
    base = {"/Type": "/Font", "/Subtype": "/Type1", "/BaseFont": "/Helvetica"}
    win = _load({**base, "/Encoding": pikepdf.Name.WinAnsiEncoding})
    mac = _load({**base, "/Encoding": pikepdf.Name.MacRomanEncoding})
    assert win.encode("é") == b"\xe9" and mac.encode("é") == b"\x8e"
    differences = pikepdf.Dictionary(BaseEncoding=pikepdf.Name.MacRomanEncoding,
                                     Differences=pikepdf.Array([65, pikepdf.Name.eacute]))
    assert _load({**base, "/Encoding": differences}).encode("é") == b"A"
    default_base = pikepdf.Dictionary(Differences=pikepdf.Array([65, pikepdf.Name.eacute]))
    assert _load({**base, "/Encoding": default_base}).encode("é") == b"A"
    for unknown in (pikepdf.Name.StandardEncoding, pikepdf.Name.MacExpertEncoding,
                    pikepdf.Dictionary(BaseEncoding=pikepdf.Name.StandardEncoding)):
        font = _load({**base, "/Encoding": unknown})
        assert not font.can_encode("a")
        assert font.width("a", 10) == 0 or font.code_width(97) > 0  # still measurable for advances


def test_font_cache_keeps_direct_font_objects_alive():
    cache: dict = {}
    font = pikepdf.Dictionary({"/Type": "/Font", "/Subtype": "/Type1", "/BaseFont": "/Helvetica"})
    resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    first = content_font(resources, "/F1", cache)
    assert first is not None
    ((key, (obj, cached)),) = cache.items()
    assert cached is first and key == id(obj)  # the cached object pins the id used as key


def test_label_value_rows_are_not_read_as_columns():
    from io import BytesIO

    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    rows = [("Languages:", "Python, SQL, Scala, Go"), ("Data:", "Spark, Kafka, Airflow, dbt, MLflow"),
            ("Cloud:", "AWS, Docker, Kubernetes"), ("Tools:", "Git, Terraform, Grafana, Jira, Looker"),
            ("2019 - 2021", "Acme Corp, Data Engineer on the platform team")]
    out = BytesIO()
    pdf = canvas.Canvas(out, pagesize=letter)
    pdf.setFont("Helvetica", 10)
    for n, (label, value) in enumerate(rows):
        pdf.drawString(72, 700 - 16 * n, label)
        pdf.drawString(180, 700 - 16 * n, value)
    pdf.save()
    texts = [p.text for p in pdf_paragraphs(out.getvalue())]
    assert texts == [f"{label} {value}" for label, value in rows]
