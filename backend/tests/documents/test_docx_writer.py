from __future__ import annotations

import pytest
from lxml import etree

from roletailor.documents import EditRejected, apply_block_edits, read_docx
from tests.documents.helpers import append_paragraph_xml, paragraph_xml, zip_parts
from tests.fixtures import make_classic_resume, make_table_resume

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@pytest.fixture(scope="module")
def classic_bytes() -> bytes:
    return make_classic_resume()


def _assert_only_changed(before: bytes, after: bytes, changed: set[str]) -> None:
    """Every paragraph outside `changed` serializes identically; other parts are untouched."""
    old, new = paragraph_xml(before), paragraph_xml(after)
    assert old.keys() == new.keys()
    assert {bid for bid in old if old[bid] != new[bid]} == changed
    old_parts, new_parts = zip_parts(before), zip_parts(after)
    assert old_parts.keys() == new_parts.keys()
    for name in old_parts:
        if name != "word/document.xml":
            assert old_parts[name] == new_parts[name], name


def test_no_edits_round_trip_is_identity(classic_bytes):
    assert apply_block_edits(classic_bytes, {}) == classic_bytes
    same_text = {b.id: b.text for b in read_docx(classic_bytes).blocks}
    assert apply_block_edits(classic_bytes, same_text) == classic_bytes


def test_document_xml_prolog_and_untouched_bytes_preserved(classic_bytes):
    after = apply_block_edits(classic_bytes, {"p3": "Shorter summary."})
    old_xml = zip_parts(classic_bytes)["word/document.xml"]
    new_xml = zip_parts(after)["word/document.xml"]
    prolog = old_xml.split(b"<w:document", 1)[0]
    assert new_xml.startswith(prolog)
    old_head, old_tail = old_xml.split(b"Data and machine learning", 1)
    assert new_xml.startswith(old_head)  # everything before the edit is byte-identical
    assert new_xml.endswith(old_tail.split(b"</w:p>", 1)[1])  # and everything after


def test_round_trip_blocks_identical_after_unrelated_edit(classic_bytes):
    before = read_docx(classic_bytes)
    after = read_docx(apply_block_edits(classic_bytes, {"p3": "New summary."}))
    for old, new in zip(before.blocks, after.blocks, strict=True):
        if old.id != "p3":
            assert old == new


def test_bold_label_run_survives_value_edit(classic_bytes):
    new_text = "Languages: Python, SQL, Scala, Go, Rust"
    after = apply_block_edits(classic_bytes, {"p18": new_text})
    block = read_docx(after).block("p18")
    assert block.text == new_text
    assert block.run_styles == [{"bold": True, "len": 10}, {"len": len(new_text) - 10}]
    _assert_only_changed(classic_bytes, after, {"p18"})


def test_value_replaced_entirely_keeps_label(classic_bytes):
    after = apply_block_edits(classic_bytes, {"p18": "Languages: Java"})
    block = read_docx(after).block("p18")
    assert block.run_styles == [{"bold": True, "len": 10}, {"len": 5}]


def test_insertion_at_run_boundary_goes_to_following_run(classic_bytes):
    after = apply_block_edits(classic_bytes, {"p20": "Cloud: GCP, AWS (S3, EMR, SageMaker, Glue), "
                                                     "Docker, Kubernetes, Terraform"})
    styles = read_docx(after).block("p20").run_styles
    assert styles[0] == {"bold": True, "len": len("Cloud:")}


def test_italic_title_edit_keeps_company_and_date_runs(classic_bytes):
    new_text = "Northwind Analytics — Staff Data Engineer\tMar 2021 – Present"
    after = apply_block_edits(classic_bytes, {"p5": new_text})
    block = read_docx(after).block("p5")
    assert block.text == new_text
    assert block.run_styles[0] == {"bold": True, "len": len("Northwind Analytics")}
    assert block.run_styles[2] == {"italic": True, "len": len("Staff Data Engineer")}
    assert block.run_styles[3] == {"len": len("\tMar 2021 – Present")}
    _assert_only_changed(classic_bytes, after, {"p5"})


def test_change_spanning_runs_merges_into_first_run(classic_bytes):
    after = apply_block_edits(classic_bytes, {"p5": "Northwind Labs\tMar 2021 – Present"})
    block = read_docx(after).block("p5")
    assert block.text == "Northwind Labs\tMar 2021 – Present"
    assert block.run_styles == [{"bold": True, "len": 14}, {"len": len("\tMar 2021 – Present")}]


def test_tabs_and_breaks_written_as_elements(classic_bytes):
    new_text = "B.S. Computer Science\nMinor in Statistics\nDean's List\t2015"
    after = apply_block_edits(classic_bytes, {"p23": new_text})
    assert read_docx(after).block("p23").text == new_text
    para = etree.fromstring(paragraph_xml(after)["p23"])
    assert len(para.findall(f".//{W}br")) == 2
    assert len(para.findall(f".//{W}tab")) == 1
    assert "\t" not in "".join(t.text for t in para.iter(f"{W}t"))


def test_whitespace_preserved(classic_bytes):
    after = apply_block_edits(classic_bytes, {"p3": "  padded summary  "})
    assert read_docx(after).block("p3").text == "  padded summary  "
    para = etree.fromstring(paragraph_xml(after)["p3"])
    space = "{http://www.w3.org/XML/1998/namespace}space"
    assert all(t.get(space) == "preserve" for t in para.iter(f"{W}t"))


def test_carriage_returns_normalized(classic_bytes):
    after = apply_block_edits(classic_bytes, {"p3": "one\r\ntwo\rthree"})
    assert read_docx(after).block("p3").text == "one\ntwo\nthree"


def test_delete_all_text(classic_bytes):
    after = apply_block_edits(classic_bytes, {"p5": ""})
    assert read_docx(after).block("p5").text == ""
    assert etree.fromstring(paragraph_xml(after)["p5"]).find(f"{W}r") is None


def test_empty_paragraph_gets_run_formatted_like_paragraph_mark():
    clean = append_paragraph_xml(make_classic_resume(),
                                 "<w:p><w:pPr><w:rPr><w:i/></w:rPr></w:pPr></w:p>")
    last = read_docx(clean).blocks[-1]
    after = apply_block_edits(clean, {last.id: "Volunteer: Code.org mentor"})
    block = read_docx(after).block(last.id)
    assert block.text == "Volunteer: Code.org mentor"
    assert block.run_styles == [{"italic": True, "len": len(block.text)}]


def test_table_paragraph_edit():
    data = make_table_resume()
    after = apply_block_edits(data, {"t0r0c0p1": "Python, SQL, Spark, dbt"})
    assert read_docx(after).block("t0r0c0p1").text == "Python, SQL, Spark, dbt"
    _assert_only_changed(data, after, {"t0r0c0p1"})


def test_nested_table_paragraph_edit():
    data = make_table_resume()
    after = apply_block_edits(data, {"t0r0c0t0r1c1p0": "Advanced"})
    assert read_docx(after).block("t0r0c0t0r1c1p0").text == "Advanced"


def test_unknown_block_rejected(classic_bytes):
    with pytest.raises(EditRejected, match="unknown"):
        apply_block_edits(classic_bytes, {"p999": "x"})


def test_non_editable_block_rejected():
    with pytest.raises(EditRejected, match="hyperlink"):
        apply_block_edits(make_table_resume(), {"p1": "new contact"})


def test_rejection_is_atomic(classic_bytes):
    with pytest.raises(EditRejected):
        apply_block_edits(classic_bytes, {"p3": "fine", "nope": "bad"})


def test_control_characters_rejected(classic_bytes):
    with pytest.raises(EditRejected, match="control"):
        apply_block_edits(classic_bytes, {"p3": "bad\x07bell"})


@pytest.mark.parametrize(
    "new_text",
    [
        "Designed a streaming pipeline",
        "Architected a Kafka + Spark streaming feature pipeline serving 40M events/day",
        "X",
        "Designed a streaming feature pipeline on Kafka and Spark Structured Streaming serving "
        "40M events/day to real-time fraud and credit-risk models.",
    ],
)
def test_reader_and_writer_agree_on_text(classic_bytes, new_text):
    after = apply_block_edits(classic_bytes, {"p6": new_text, "p22": f"UW\t{new_text[:4]}"})
    doc = read_docx(after)
    assert doc.block("p6").text == new_text
    assert doc.block("p6").is_list_item
    assert doc.block("p22").text == f"UW\t{new_text[:4]}"
    _assert_only_changed(classic_bytes, after, {"p6", "p22"})
