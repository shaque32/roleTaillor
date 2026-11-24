from __future__ import annotations

import pytest
from docx.shared import Pt

from roletailor.documents import InvalidDocument, read_docx
from tests.documents.helpers import append_paragraph_xml, modify_docx
from tests.fixtures import make_classic_resume, make_table_resume


@pytest.fixture(scope="module")
def classic():
    return read_docx(make_classic_resume())


@pytest.fixture(scope="module")
def table():
    return read_docx(make_table_resume())


def test_classic_block_ids_are_sequential(classic):
    assert [b.id for b in classic.blocks] == [f"p{n}" for n in range(len(classic.blocks))]
    assert classic.source_format == "docx"
    assert classic.supports_in_place_edit


def test_empty_paragraphs_are_counted():
    data = modify_docx(make_classic_resume(), lambda doc: doc.paragraphs[0].insert_paragraph_before(""))
    doc = read_docx(data)
    assert doc.block("p0").text == ""
    assert doc.block("p1").text == "Priya Raman"


def test_headings_lists_and_name(classic):
    headings = [b.text for b in classic.blocks if b.is_heading]
    assert headings == ["SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION", "CERTIFICATIONS"]
    assert not classic.block("p0").is_heading  # the name line
    bullets = [b for b in classic.blocks if b.is_list_item]
    assert len(bullets) == 11
    assert all(b.style_name == "List Bullet" for b in bullets)


def test_run_styles_capture_formatting(classic):
    role = classic.block("p5")
    assert role.text == "Northwind Analytics — Senior Data Engineer\tMar 2021 – Present"
    assert role.run_styles[0] == {"bold": True, "len": len("Northwind Analytics")}
    assert role.run_styles[2] == {"italic": True, "len": len("Senior Data Engineer")}
    assert sum(t["len"] for t in role.run_styles) == len(role.text)
    assert classic.block("p0").run_styles == [{"bold": True, "size": 20.0, "len": 11}]
    assert classic.block("p2").run_styles[0]["color"] == "1F3A5F"


def test_tab_and_break_map_to_control_chars(classic):
    assert classic.block("p22").text == "University of Washington\t2016"
    assert classic.block("p23").text == "B.S. Computer Science\nMinor in Statistics"


def test_layout_metadata(classic):
    meta = classic.layout_metadata
    assert meta["page_width_in"] == 8.5 and meta["page_height_in"] == 11.0
    assert meta["orientation"] == "portrait"
    assert meta["margins_in"] == {"top": 0.6, "bottom": 0.6, "left": 0.75, "right": 0.75}
    assert meta["section_count"] == 1
    assert meta["default_font"] == "Calibri"
    assert meta["default_font_size_pt"] == 10.5
    assert meta["paragraph_count"] == len(classic.blocks)
    assert meta["header_count"] == 0


def test_classic_has_no_findings(classic):
    assert classic.findings == []


def test_table_block_ids_including_nested(table):
    ids = [b.id for b in table.blocks]
    assert ids[:2] == ["p0", "p1"]
    assert "t0r0c0p0" in ids and "t0r0c1p0" in ids
    assert [
        i for i in ids if i.startswith("t0r0c0t0")
    ] == ["t0r0c0t0r0c0p0", "t0r0c0t0r0c1p0", "t0r0c0t0r1c0p0", "t0r0c0t0r1c1p0"]
    assert table.block("t0r0c0t0r1c0p0").text == "SQL"
    assert all(b.kind == "table_paragraph" for b in table.blocks if b.id.startswith("t"))
    assert table.layout_metadata["table_count"] == 1


def test_heading_style_detection(table):
    skills = table.block("t0r0c0p0")
    assert skills.is_heading and skills.style_name.lower() == "heading 2"
    assert not table.block("p0").is_heading  # Title style is the name, not a section


def test_hyperlink_paragraph_is_locked(table):
    contact = table.block("p1")
    assert not contact.editable
    assert contact.text == "Austin, TX | marcus.okafor@example.com | (512) 555-0193"
    codes = {f["code"] for f in table.findings}
    assert {"table_layout", "locked_block"} <= codes
    locked = next(f for f in table.findings if f["code"] == "locked_block")
    assert locked["block_id"] == "p1" and "hyperlink" in locked["detail"]


def test_missing_sections_detected():
    def drop_education(doc) -> None:
        for para in doc.paragraphs:
            if para.text in ("EDUCATION", "SKILLS"):
                para.text = "Other"

    doc = read_docx(modify_docx(make_classic_resume(), drop_education))
    details = {f["detail"] for f in doc.findings if f["code"] == "missing_section"}
    assert details == {"No education section found", "No skills section found"}


@pytest.mark.parametrize(
    ("inner", "reason"),
    [
        ('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>PAGE</w:instrText>'
         '</w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>', "field"),
        ('<w:fldSimple w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>', "field"),
        ('<w:ins w:id="1" w:author="a"><w:r><w:t>new</w:t></w:r></w:ins>', "tracked change"),
        ('<w:sdt><w:sdtContent><w:r><w:t>cc</w:t></w:r></w:sdtContent></w:sdt>',
         "content control"),
        ('<w:r><w:t>a</w:t><w:br w:type="page"/></w:r>', "page or column break"),
    ],
)
def test_non_editable_markup(inner, reason):
    data = append_paragraph_xml(make_classic_resume(), f"<w:p><w:r><w:t>x </w:t></w:r>{inner}</w:p>")
    doc = read_docx(data)
    block = doc.blocks[-1]
    assert not block.editable
    assert block.text.startswith("x ")
    assert any(f.get("block_id") == block.id and reason in f["detail"] for f in doc.findings)


def test_deleted_text_is_not_extracted():
    data = append_paragraph_xml(
        make_classic_resume(),
        '<w:p><w:r><w:t>kept</w:t></w:r><w:del w:id="2" w:author="a"><w:r>'
        "<w:delText>gone</w:delText></w:r></w:del></w:p>",
    )
    block = read_docx(data).blocks[-1]
    assert block.text == "kept" and not block.editable


def test_text_box_text_is_surfaced_and_flagged():
    xml = (
        '<w:p><w:r><w:t>Anchor</w:t></w:r><w:r><mc:AlternateContent '
        'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
        "<mc:Choice Requires=\"wps\"><w:drawing><w:txbxContent>"
        "<w:p><w:r><w:t>Boxed contact</w:t></w:r></w:p></w:txbxContent></w:drawing></mc:Choice>"
        "<mc:Fallback><w:pict><w:txbxContent><w:p><w:r><w:t>Boxed contact</w:t></w:r></w:p>"
        "</w:txbxContent></w:pict></mc:Fallback></mc:AlternateContent></w:r></w:p>"
    )
    doc = read_docx(append_paragraph_xml(make_classic_resume(), xml))
    block = doc.blocks[-1]
    assert block.text == "Anchor\nBoxed contact"
    assert not block.editable
    assert "text_in_text_box" in {f["code"] for f in doc.findings}


def test_images_and_mixed_fonts_findings():
    xml = "<w:p><w:r><w:drawing/></w:r></w:p>"

    def mixed_fonts(doc) -> None:
        for para, font in zip(doc.paragraphs[3:7], ["Arial", "Georgia", "Verdana", "Garamond"],
                              strict=True):
            for run in para.runs:
                run.font.name = font
                run.font.size = Pt(10)

    data = append_paragraph_xml(modify_docx(make_classic_resume(), mixed_fonts), xml)
    codes = {f["code"] for f in read_docx(data).findings}
    assert {"images_present", "mixed_fonts"} <= codes


def test_header_text_is_recorded_not_extracted():
    def add_header(doc) -> None:
        doc.sections[0].header.paragraphs[0].text = "Confidential header contact"

    doc = read_docx(modify_docx(make_classic_resume(), add_header))
    assert doc.layout_metadata["header_count"] == 1
    assert doc.layout_metadata["header_footer_has_text"] is True
    assert all("Confidential" not in b.text for b in doc.blocks)
    assert "header_footer_text" in {f["code"] for f in doc.findings}


def test_manual_bullets_and_numbering_detected():
    xml = (
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
        "<w:r><w:t>Numbered item</w:t></w:r></w:p>"
    )
    data = append_paragraph_xml(make_classic_resume(), xml)
    data = append_paragraph_xml(data, "<w:p><w:r><w:t>• Manual bullet</w:t></w:r></w:p>")
    blocks = read_docx(data).blocks
    assert blocks[-2].is_list_item and blocks[-1].is_list_item


def test_invalid_bytes_raise():
    with pytest.raises(InvalidDocument):
        read_docx(b"not a zip")
