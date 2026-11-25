from __future__ import annotations

from roletailor.documents import read_plain_text

RESUME = """Ada Lovelace
ada@example.com

SUMMARY
Data engineer with 7 years building streaming systems.

EXPERIENCE
Senior Data Engineer, Northwind
• Built Kafka pipelines serving 40M events/day
- Cut batch latency by 60%
* Mentored four engineers

EDUCATION
BSc Mathematics, University of London

SKILLS
Python, SQL, Spark
"""


def test_blocks_ids_and_kinds():
    doc = read_plain_text(RESUME)
    assert doc.source_format == "text" and doc.supports_in_place_edit is False
    assert [b.id for b in doc.blocks] == [f"t{i}" for i in range(len(doc.blocks))]
    assert all(b.kind == "text_line" for b in doc.blocks)
    assert doc.layout_metadata["source"] == "paste"
    assert doc.layout_metadata["line_count"] == len(doc.blocks)


def test_headings_and_bullets():
    blocks = {b.text: b for b in read_plain_text(RESUME).blocks}
    for heading in ("SUMMARY", "EXPERIENCE", "EDUCATION", "SKILLS"):
        assert blocks[heading].is_heading
    for bullet in ("Built Kafka pipelines serving 40M events/day", "Cut batch latency by 60%",
                   "Mentored four engineers"):
        assert blocks[bullet].is_list_item and not blocks[bullet].is_heading
    assert not blocks["Ada Lovelace"].is_list_item


def test_numbered_list_is_stripped():
    blocks = read_plain_text("Experience\n1. First thing\n2) Second thing\n").blocks
    assert [(b.text, b.is_list_item) for b in blocks[1:]] == [
        ("First thing", True), ("Second thing", True)]


def test_wrap_merging():
    text = ("Experience\n- Built pipelines that process\nlarge volumes of data\n"
            "- Led a team of five,\nacross two time zones\nNext paragraph starts here\n")
    texts = [b.text for b in read_plain_text(text).blocks]
    assert "Built pipelines that process large volumes of data" in texts
    assert "Led a team of five, across two time zones" in texts
    assert "Next paragraph starts here" in texts


def test_no_merge_across_blank_line_sentence_end_or_heading():
    text = "Summary\nDid things.\nlower start after sentence\n\nlower after blank\nSkills\nPython\n"
    texts = [b.text for b in read_plain_text(text).blocks]
    assert "Did things." in texts and "lower start after sentence" in texts
    assert "lower after blank" in texts
    assert "Skills" in texts and "Python" in texts


def test_crlf_cr_control_chars_and_spaces():
    doc = read_plain_text("Summary\r\nHello\x00  \t world\rSkills\r\n")
    assert [b.text for b in doc.blocks] == ["Summary", "Hello world", "Skills"]


def test_empty_input():
    for empty in ("", "   \n\t\r\n"):
        doc = read_plain_text(empty)
        assert doc.blocks == [] and doc.findings[0]["code"] == "empty_text"


def test_missing_section_findings():
    doc = read_plain_text("Experience\nDid stuff at Acme\n")
    codes = {f["detail"] for f in doc.findings}
    assert "No education section found" in codes and "No skills section found" in codes
    assert not read_plain_text(RESUME).findings


def test_wrapped_bullet_that_looks_like_a_heading_keeps_its_continuation():
    doc = read_plain_text("Experience\n- CI/CD\nand release automation")
    assert [(b.text, b.is_list_item) for b in doc.blocks] == [
        ("Experience", False), ("CI/CD and release automation", True)]
