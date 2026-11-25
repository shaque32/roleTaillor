"""Clean single-column ATS-friendly DOCX template for guided resumes and PDF uploads."""

from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph

from .model import Block

FONT = "Calibri"
BODY_PT = 10.5
NAME_PT = 18
CONTACT_PT = 9.5
HEADING_PT = 11
MARGIN_IN = 0.7
PAGE_WIDTH_IN = 8.5
CONTENT_WIDTH = Inches(PAGE_WIDTH_IN - 2 * MARGIN_IN)
ACCENT = RGBColor(0x1F, 0x3A, 0x5F)
_PBDR_SUCCESSORS = (
    "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
    "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
    "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
    "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment", "w:textboxTightWrap",
    "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
)


def render_structured_docx(blocks: list[Block], sections_meta: list[dict] | None = None) -> bytes:
    """Render blocks into a fresh, single-column resume.

    Blocks before the first heading form the header: the first is the name, the rest
    contact lines. Headings become bold section titles, list items bullets, and a tab in
    a line right-aligns what follows it (dates). `run_styles` bold/italic are honoured
    when their lengths cover the text exactly.

    `sections_meta` (e.g. `Section.model_dump()` dicts with `title`, `block_ids` and an
    optional `heading_block_id`) overrides the order: each section's title is rendered as
    a heading followed by its blocks. Blocks no section references become the header.
    """
    doc = Document()
    _configure(doc)
    header, body = _arrange(blocks, sections_meta)
    for i, block in enumerate(header):
        _header_line(doc, block, is_name=i == 0)
    previous: Block | None = None
    for block in body:
        if block.is_heading:
            _heading(doc, block.text)
        else:
            _body_line(doc, block, new_entry=bool(previous and previous.is_list_item))
        previous = block
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def _arrange(blocks: list[Block], sections_meta: list[dict] | None) -> tuple[list[Block],
                                                                            list[Block]]:
    texted = [b for b in blocks if b.text.strip()]
    if not sections_meta:
        first_heading = next((i for i, b in enumerate(texted) if b.is_heading), len(texted))
        return texted[:first_heading], texted[first_heading:]

    by_id = {b.id: b for b in texted}
    referenced: set[str] = set()
    body: list[Block] = []
    for section in sections_meta:
        ids = [i for i in section.get("block_ids", []) if i in by_id]
        referenced.update(ids)
        if heading_id := section.get("heading_block_id"):
            referenced.add(heading_id)
        if title := (section.get("title") or "").strip():
            body.append(Block(id=f"title-{len(body)}", text=title, is_heading=True))
        body.extend(by_id[i] for i in ids if i != heading_id)
    header = [b for b in texted if b.id not in referenced]
    return header, body


# --------------------------------------------------------------------------
# Document setup
# --------------------------------------------------------------------------


def _configure(doc: DocxDocument) -> None:
    for section in doc.sections:
        section.page_width, section.page_height = Inches(PAGE_WIDTH_IN), Inches(11)
        section.left_margin = section.right_margin = Inches(MARGIN_IN)
        section.top_margin = section.bottom_margin = Inches(0.6)
    for name in ("Normal", "List Bullet"):
        style = doc.styles[name]
        style.font.name = FONT
        style.font.size = Pt(BODY_PT)
        style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
        fmt = style.paragraph_format
        fmt.space_before, fmt.space_after, fmt.line_spacing = Pt(0), Pt(2), 1.08
    doc.styles["List Bullet"].paragraph_format.space_after = Pt(1)


# --------------------------------------------------------------------------
# Paragraph builders
# --------------------------------------------------------------------------


def _header_line(doc: DocxDocument, block: Block, *, is_name: bool) -> None:
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(4 if is_name else 1)
    run = para.add_run(block.text.replace("\t", "  |  ").replace("\n", "  |  "))
    run.font.size = Pt(NAME_PT if is_name else CONTACT_PT)
    run.font.bold = is_name
    if is_name:
        run.font.color.rgb = ACCENT


def _heading(doc: DocxDocument, text: str) -> None:
    para = doc.add_paragraph()
    fmt = para.paragraph_format
    fmt.space_before, fmt.space_after, fmt.keep_with_next = Pt(10), Pt(3), True
    run = para.add_run(text.strip().rstrip(":"))
    run.font.bold = True
    run.font.all_caps = True
    run.font.size = Pt(HEADING_PT)
    run.font.color.rgb = ACCENT
    _bottom_border(para)


def _bottom_border(para: Paragraph) -> None:
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"),
                       ("w:color", "1F3A5F")):
        bottom.set(qn(key), value)
    borders.append(bottom)
    # CT_PPr children are order-sensitive; pBdr precedes these siblings.
    para._p.get_or_add_pPr().insert_element_before(borders, *_PBDR_SUCCESSORS)


def _body_line(doc: DocxDocument, block: Block, *, new_entry: bool) -> None:
    """`new_entry` adds breathing room above a non-bullet line that follows bullets
    (typically the next role's header)."""
    para = doc.add_paragraph(style="List Bullet" if block.is_list_item else None)
    if new_entry and not block.is_list_item:
        para.paragraph_format.space_before = Pt(5)
    if "\t" in block.text:
        para.paragraph_format.tab_stops.add_tab_stop(CONTENT_WIDTH, WD_TAB_ALIGNMENT.RIGHT)
    for text, style in _styled_segments(block):
        # python-docx maps \t to w:tab and \n to w:br.
        run = para.add_run(text)
        run.font.bold = style.get("bold") or None
        run.font.italic = style.get("italic") or None


def _styled_segments(block: Block) -> list[tuple[str, dict]]:
    lengths = [tok.get("len", 0) for tok in block.run_styles]
    if not lengths or sum(lengths) != len(block.text):
        return [(block.text, {})]
    segments, pos = [], 0
    for tok, length in zip(block.run_styles, lengths, strict=True):
        segments.append((block.text[pos:pos + length], tok))
        pos += length
    return segments
