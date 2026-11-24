"""Parse a DOCX into contract `Block`s plus layout metadata and ATS findings."""

from __future__ import annotations

from dataclasses import dataclass, field

from lxml import etree

from ._analysis import looks_like_heading, missing_section_findings, strip_bullet
from ._ooxml import (
    NS,
    DocxPackage,
    ParagraphRef,
    body_of,
    iter_paragraphs,
    local,
    non_editable_reason,
    paragraph_runs,
    run_text,
    textbox_texts,
    w,
    wattr,
)
from ._styles import StyleSheet, load_stylesheet, run_font, run_size_pt, toggle_on
from .model import Block, ParsedDocument

TWIPS_PER_INCH = 1440
MAX_DISTINCT_FONTS = 3

_REASON_TEXT = {
    "hyperlink": "a hyperlink",
    "field": "a field (e.g. page number or auto text)",
    "drawing": "an image or drawing",
    "text_box": "a text box",
    "tracked_change": "tracked changes",
    "content_control": "a content control",
    "page_break": "a page or column break",
    "note_reference": "a footnote/endnote reference",
    "comment": "a comment",
    "unsupported_markup": "markup the editor does not rewrite",
}

_SECTPR_XPATH = etree.XPath("./w:sectPr | .//w:pPr/w:sectPr", namespaces=NS)
_IMAGE_XPATH = etree.XPath(
    ".//w:drawing[not(.//w:txbxContent)] | .//w:pict[not(.//w:txbxContent)]", namespaces=NS
)


@dataclass
class _Scan:
    """A block plus facts about its paragraph that only document-level findings need."""

    block: Block
    reason: str | None
    has_textbox: bool
    fonts: set[str] = field(default_factory=set)


def read_docx(data: bytes) -> ParsedDocument:
    """Parse DOCX bytes. Block ids follow the contract in `model.Block`.

    Text-box text is appended (after a newline) to the text of its anchoring paragraph,
    which is then non-editable; header/footer text is never part of a block.
    """
    pkg = DocxPackage(data)
    document = pkg.xml(pkg.main_part)
    assert document is not None  # DocxPackage guarantees the main part exists
    body = body_of(document)
    sheet = load_stylesheet(pkg)

    scans: list[_Scan] = []
    seen_text = False
    for ref in iter_paragraphs(body):
        scan = _scan_paragraph(ref, sheet, first_text_line=not seen_text)
        seen_text = seen_text or bool(scan.block.text.strip())
        scans.append(scan)

    blocks = [s.block for s in scans]
    headers_footers = _header_footer_summary(pkg)
    return ParsedDocument(
        source_format="docx",
        blocks=blocks,
        layout_metadata=_layout_metadata(body, sheet, blocks) | headers_footers,
        findings=_findings(body, sheet, scans, headers_footers),
        supports_in_place_edit=True,
    )


# --------------------------------------------------------------------------
# Paragraph scan
# --------------------------------------------------------------------------


def _run_bold(rpr: etree._Element | None, sheet: StyleSheet, para_bold: bool) -> bool:
    direct = None if rpr is None else rpr.find(w("b"))
    if direct is not None:
        return toggle_on(direct)
    char_style = wattr(None if rpr is None else rpr.find(w("rStyle")), "val")
    return sheet.is_bold(char_style) if char_style else para_bold


def _run_style(r: etree._Element, length: int, sheet: StyleSheet, para_bold: bool) -> dict:
    rpr = r.find(w("rPr"))
    token: dict = {}
    if _run_bold(rpr, sheet, para_bold):
        token["bold"] = True
    if rpr is not None:
        if toggle_on(rpr.find(w("i"))):
            token["italic"] = True
        underline = wattr(rpr.find(w("u")), "val")
        if underline and underline != "none":
            token["underline"] = True
        if font := run_font(rpr, sheet.theme_fonts):
            token["font"] = font
        if (size := run_size_pt(rpr)) is not None:
            token["size"] = size
        color = wattr(rpr.find(w("color")), "val")
        if color and color != "auto":
            token["color"] = color
    token["len"] = length
    return token


def _is_list_item(ppr: etree._Element | None, style_id: str | None, text: str,
                  sheet: StyleSheet) -> bool:
    num_id = wattr(None if ppr is None else ppr.find(f"{w('numPr')}/{w('numId')}"), "val")
    if num_id is not None:
        return num_id != "0"
    return sheet.is_list(style_id) or strip_bullet(text)[1]


def _scan_paragraph(ref: ParagraphRef, sheet: StyleSheet, *, first_text_line: bool) -> _Scan:
    p = ref.element
    ppr = p.find(w("pPr"))
    style_id = wattr(None if ppr is None else ppr.find(w("pStyle")), "val")
    para_bold = sheet.is_bold(style_id)

    runs = [(r, run_text(r)) for r in paragraph_runs(p)]
    text = "".join(t for _, t in runs)
    boxes = textbox_texts(p)
    if boxes:
        text = "\n".join([text, *boxes] if text else boxes)

    styled = [(t, _run_style(r, len(t), sheet, para_bold)) for r, t in runs if t]
    run_styles = [tok for _, tok in styled]
    visible = [tok for t, tok in styled if t.strip()]
    all_bold = bool(visible) and all(tok.get("bold") for tok in visible)
    is_list = _is_list_item(ppr, style_id, text, sheet)
    is_heading = sheet.is_heading(style_id) or (
        not is_list
        and looks_like_heading(text, all_bold=all_bold, allow_caps_only=not first_text_line)
    )
    reason = non_editable_reason(ref)
    block = Block(
        id=ref.block_id,
        kind="table_paragraph" if ref.in_table else "paragraph",
        text=text,
        style_name=sheet.name(style_id) if style_id else sheet.name(sheet.default_paragraph_style),
        is_list_item=is_list,
        is_heading=is_heading,
        editable=reason is None,
        run_styles=run_styles,
    )
    fonts = {tok["font"] for tok in run_styles if "font" in tok}
    return _Scan(block=block, reason=reason, has_textbox=bool(boxes), fonts=fonts)


# --------------------------------------------------------------------------
# Layout metadata
# --------------------------------------------------------------------------


def _inches(twips: str | None) -> float | None:
    try:
        return round(int(twips or "") / TWIPS_PER_INCH, 3)
    except ValueError:
        return None


def _section_layout(sect: etree._Element | None) -> dict:
    if sect is None:
        return {}
    size = sect.find(w("pgSz"))
    margins = sect.find(w("pgMar"))
    cols = wattr(sect.find(w("cols")), "num")
    width, height = _inches(wattr(size, "w")), _inches(wattr(size, "h"))
    orientation = wattr(size, "orient") or (
        "landscape" if width and height and width > height else "portrait"
    )
    return {
        "page_width_in": width,
        "page_height_in": height,
        "orientation": orientation,
        "margins_in": {
            side: _inches(wattr(margins, side)) for side in ("top", "bottom", "left", "right")
        },
        "columns": int(cols) if cols and cols.isdigit() else 1,
    }


def _layout_metadata(body: etree._Element, sheet: StyleSheet, blocks: list[Block]) -> dict:
    sections = _SECTPR_XPATH(body)
    # The body-level sectPr (last in document order) describes the main section.
    meta = _section_layout(sections[-1] if sections else None)
    meta.update(
        section_count=max(len(sections), 1),
        default_font=sheet.default_font,
        default_font_size_pt=sheet.default_size_pt,
        paragraph_count=sum(1 for child in body if local(child) == "p"),
        table_count=sum(1 for child in body if local(child) == "tbl"),
        block_count=len(blocks),
    )
    return meta


def _part_text(pkg: DocxPackage, part: str) -> str:
    root = pkg.xml(part)
    return "" if root is None else "".join(t.text or "" for t in root.iter(w("t")))


def _header_footer_summary(pkg: DocxPackage) -> dict:
    headers = pkg.related(pkg.main_part, "/header")
    footers = pkg.related(pkg.main_part, "/footer")
    has_text = any(_part_text(pkg, part).strip() for part in headers + footers)
    return {
        "header_count": len(headers),
        "footer_count": len(footers),
        "header_footer_has_text": has_text,
    }


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


def _locked_findings(scans: list[_Scan]) -> list[dict]:
    return [
        {
            "code": "locked_block",
            "block_id": s.block.id,
            "detail": f"Block {s.block.id} contains {_REASON_TEXT[s.reason]} and is kept as-is",
        }
        for s in scans
        if s.reason and s.block.text.strip()
    ]


def _findings(body: etree._Element, sheet: StyleSheet, scans: list[_Scan],
              headers_footers: dict) -> list[dict]:
    findings: list[dict] = []
    blocks = [s.block for s in scans]
    if not any(b.text.strip() for b in blocks):
        findings.append({"code": "no_text", "detail": "The document contains no body text"})

    if boxes := sum(s.has_textbox for s in scans):
        findings.append({"code": "text_in_text_box", "detail": (
            f"{boxes} paragraph(s) anchor text boxes; many ATS parsers skip text-box content")})

    tables = {b.id.split("r", 1)[0] for b in blocks if b.kind == "table_paragraph"
              and b.text.strip()}
    if tables:
        findings.append({"code": "table_layout", "detail": (
            f"Content is laid out in {len(tables)} table(s); some ATS parsers read table "
            "cells out of order")})

    if images := len(_IMAGE_XPATH(body)):
        findings.append({"code": "images_present", "detail": (
            f"{images} image(s) or drawing(s); ATS parsers ignore images and their text")})

    fonts = {font for s in scans for font in s.fonts}
    if sheet.default_font:
        fonts.add(sheet.default_font)
    if len(fonts) > MAX_DISTINCT_FONTS:
        findings.append({"code": "mixed_fonts", "detail": (
            f"{len(fonts)} different fonts used ({', '.join(sorted(fonts))})")})

    if headers_footers["header_footer_has_text"]:
        findings.append({"code": "header_footer_text", "detail": (
            "Headers/footers contain text (often contact details), which some ATS parsers "
            "skip")})

    if any(int(c) > 1 for c in (wattr(x, "num") for x in body.iter(w("cols")))
           if c and c.isdigit()):
        findings.append({"code": "multi_column_layout", "detail": (
            "A section uses multiple text columns, which ATS parsers may read out of order")})

    findings.extend(_locked_findings(scans))
    findings.extend(missing_section_findings(blocks))
    return findings
