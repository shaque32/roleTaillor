from __future__ import annotations

import pytest

from roletailor.documents import (
    Block,
    count_pdf_pages,
    docx_to_pdf,
    read_docx,
    render_structured_docx,
)
from roletailor.documents.pdf import soffice_path
from tests.fixtures import make_classic_resume


def _sample_blocks() -> list[Block]:
    return [
        Block(id="l0", text="Ana Torres"),
        Block(id="l1", text="Denver, CO | ana@example.com"),
        Block(id="l2", text="Experience", is_heading=True),
        Block(id="l3", text="Acme Data — ML Engineer\t2020 – Present",
              run_styles=[{"bold": True, "len": 9}, {"len": 29}]),
        Block(id="l4", text="Built churn models in PyTorch.", is_list_item=True),
        Block(id="l5", text="Skills", is_heading=True),
        Block(id="l6", text="Python, SQL, Spark"),
    ]


def test_render_is_readable_and_structured():
    doc = read_docx(render_structured_docx(_sample_blocks()))
    texts = [b.text for b in doc.text_blocks()]
    assert texts == ["Ana Torres", "Denver, CO | ana@example.com", "Experience",
                     "Acme Data — ML Engineer\t2020 – Present",
                     "Built churn models in PyTorch.", "Skills", "Python, SQL, Spark"]
    by_text = {b.text: b for b in doc.blocks}
    assert by_text["Experience"].is_heading and by_text["Skills"].is_heading
    assert by_text["Built churn models in PyTorch."].is_list_item
    assert by_text["Acme Data — ML Engineer\t2020 – Present"].run_styles[0]["bold"]
    assert doc.layout_metadata["default_font"] == "Calibri"
    assert all(b.editable for b in doc.blocks)
    assert not [f for f in doc.findings if f["code"] != "missing_section"]


def test_sections_meta_controls_order_and_titles():
    blocks = _sample_blocks()
    meta = [
        {"title": "Technical Skills", "heading_block_id": "l5", "block_ids": ["l6"]},
        {"title": "Work History", "heading_block_id": "l2", "block_ids": ["l3", "l4"]},
    ]
    doc = read_docx(render_structured_docx(blocks, meta))
    texts = [b.text for b in doc.text_blocks()]
    assert texts[:3] == ["Ana Torres", "Denver, CO | ana@example.com", "Technical Skills"]
    assert texts.index("Work History") > texts.index("Python, SQL, Spark")
    assert "Experience" not in texts


def test_rerender_of_parsed_docx_round_trips_text():
    parsed = read_docx(make_classic_resume())
    rendered = read_docx(render_structured_docx(parsed.blocks))
    assert [b.text for b in rendered.text_blocks()] == [b.text for b in parsed.text_blocks()]
    assert sum(b.is_list_item for b in rendered.blocks) == 11


@pytest.mark.skipif(soffice_path() is None, reason="LibreOffice not installed")
def test_render_converts_to_single_page_pdf():
    assert count_pdf_pages(docx_to_pdf(render_structured_docx(_sample_blocks()))) == 1
