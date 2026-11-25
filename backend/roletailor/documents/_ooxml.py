"""Low-level WordprocessingML helpers shared by the DOCX reader and writer.

Both sides must agree on two things or edits land in the wrong place:

* the block-id walk (`iter_paragraphs`), and
* how a run maps to text (`run_text`): ``w:t`` is literal text, ``w:tab``/``w:ptab``
  become ``\\t`` and ``w:br``/``w:cr`` become ``\\n``.

Everything here works on raw lxml elements straight from the zip package, so parts we
do not edit are never re-serialized.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO

from lxml import etree

from .errors import InvalidDocument

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
NS = {"w": W_NS, "r": R_NS, "mc": MC_NS, "a": A_NS}

MAX_PART_BYTES = 16 * 1024 * 1024

_XML_DECL = re.compile(rb"^\s*<\?xml[^>]*\?>\s*")

# Paragraph children that carry no text and survive run surgery untouched.
_PASSIVE_PARAGRAPH_CHILDREN = frozenset(
    {"pPr", "bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd",
     "commentRangeStart", "commentRangeEnd"}
)
_PARAGRAPH_CHILD_REASONS = {
    "hyperlink": "hyperlink",
    "fldSimple": "field",
    "ins": "tracked_change",
    "del": "tracked_change",
    "moveFrom": "tracked_change",
    "moveTo": "tracked_change",
    "sdt": "content_control",
}
_TEXT_RUN_CHILDREN = frozenset(
    {"rPr", "t", "tab", "ptab", "br", "cr", "noBreakHyphen", "softHyphen",
     "lastRenderedPageBreak"}
)
_RUN_CHILD_REASONS = {
    "drawing": "drawing",
    "pict": "drawing",
    "object": "drawing",
    "fldChar": "field",
    "instrText": "field",
    "footnoteReference": "note_reference",
    "endnoteReference": "note_reference",
    "commentReference": "comment",
}


def w(tag: str) -> str:
    """Clark-notation name for a WordprocessingML tag."""
    return f"{{{W_NS}}}{tag}"


def local(el: etree._Element) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def wattr(el: etree._Element | None, name: str) -> str | None:
    return None if el is None else el.get(w(name))


_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def parse_xml(data: bytes) -> etree._Element:
    try:
        return etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as exc:
        raise InvalidDocument(f"malformed XML part: {exc}") from exc


def serialize_like(original: bytes, root: etree._Element) -> bytes:
    """Serialize `root` reusing the original part's XML declaration verbatim."""
    match = _XML_DECL.match(original)
    prolog = match.group(0) if match else b""
    return prolog + etree.tostring(root.getroottree(), encoding="UTF-8", xml_declaration=False)


class DocxPackage:
    """Read-only view of a DOCX zip with relationship resolution."""

    def __init__(self, data: bytes) -> None:
        try:
            self.zip = zipfile.ZipFile(BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise InvalidDocument("not a DOCX (zip) file") from exc
        self._names = set(self.zip.namelist())
        self.main_part = self._main_part_name()

    def read(self, name: str) -> bytes | None:
        if name not in self._names:
            return None
        if self.zip.getinfo(name).file_size > MAX_PART_BYTES:
            raise InvalidDocument(f"part {name} exceeds {MAX_PART_BYTES} bytes")
        return self.zip.read(name)

    def xml(self, name: str) -> etree._Element | None:
        raw = self.read(name)
        return None if raw is None else parse_xml(raw)

    def related(self, source: str, rel_suffix: str) -> list[str]:
        """Internal part names related to `source` whose type ends with `rel_suffix`."""
        folder, base = posixpath.split(source)
        rels = self.xml(posixpath.join(folder, "_rels", base + ".rels"))
        if rels is None:
            return []
        parts = []
        for rel in rels.iter(f"{{{PKG_REL_NS}}}Relationship"):
            if rel.get("TargetMode") == "External" or not rel.get("Type", "").endswith(rel_suffix):
                continue
            target = rel.get("Target", "")
            name = target.lstrip("/") if target.startswith("/") else posixpath.normpath(
                posixpath.join(folder, target)
            )
            if name in self._names:
                parts.append(name)
        return parts

    def _main_part_name(self) -> str:
        for name in self.related("", "/officeDocument"):
            return name
        if "word/document.xml" in self._names:
            return "word/document.xml"
        raise InvalidDocument("package has no main document part")


def body_of(document: etree._Element) -> etree._Element:
    body = document.find(w("body"))
    if body is None:
        raise InvalidDocument("document has no w:body")
    return body


# --------------------------------------------------------------------------
# Block-id walk
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ParagraphRef:
    block_id: str
    element: etree._Element
    in_table: bool
    # Inside a content control (w:sdt) or custom XML wrapper.
    locked: bool


def _content(parent: etree._Element, locked: bool) -> Iterator[tuple[etree._Element, bool]]:
    """Yield w:p / w:tbl children, flattening content controls and custom XML."""
    for child in parent:
        name = local(child)
        if name in ("p", "tbl"):
            yield child, locked
        elif name == "sdt":
            content = child.find(w("sdtContent"))
            if content is not None:
                yield from _content(content, True)
        elif name == "customXml":
            yield from _content(child, True)


def _children(
    parent: etree._Element, tag: str, locked: bool
) -> Iterator[tuple[etree._Element, bool]]:
    """Yield `tag` children (rows or cells), flattening row/cell-level content controls."""
    for child in parent:
        name = local(child)
        if name == tag:
            yield child, locked
        elif name == "sdt":
            content = child.find(w("sdtContent"))
            if content is not None:
                yield from _children(content, tag, True)
        elif name == "customXml":
            yield from _children(child, tag, True)


def _iter_table(tbl: etree._Element, prefix: str, locked: bool) -> Iterator[ParagraphRef]:
    """Nested tables get ids like ``t0r1c0t0r0c1p0`` (cell prefix + nested table index)."""
    for r, (row, row_locked) in enumerate(_children(tbl, "tr", locked)):
        for c, (cell, cell_locked) in enumerate(_children(row, "tc", row_locked)):
            cell_prefix = f"{prefix}r{r}c{c}"
            n = k = 0
            for el, el_locked in _content(cell, cell_locked):
                if local(el) == "p":
                    yield ParagraphRef(f"{cell_prefix}p{n}", el, True, el_locked)
                    n += 1
                else:
                    yield from _iter_table(el, f"{cell_prefix}t{k}", el_locked)
                    k += 1


def iter_paragraphs(body: etree._Element) -> Iterator[ParagraphRef]:
    """Walk the body in document order, assigning contract block ids."""
    p_index = t_index = 0
    for el, locked in _content(body, False):
        if local(el) == "p":
            yield ParagraphRef(f"p{p_index}", el, False, locked)
            p_index += 1
        else:
            yield from _iter_table(el, f"t{t_index}", locked)
            t_index += 1


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------

_RUN_XPATH = etree.XPath(
    "./descendant::w:r[not(ancestor::w:txbxContent) and not(ancestor::w:del)"
    " and not(ancestor::w:moveFrom) and not(ancestor::mc:Fallback)]",
    namespaces=NS,
)
# Runs of a paragraph that itself lives inside a text box.
_BOXED_RUN_XPATH = etree.XPath(
    "./descendant::w:r[not(ancestor::w:del) and not(ancestor::w:moveFrom)]", namespaces=NS
)
_TEXTBOX_XPATH = etree.XPath(
    ".//w:txbxContent[not(ancestor::w:txbxContent) and not(ancestor::mc:Fallback)]",
    namespaces=NS,
)


def paragraph_runs(p: etree._Element) -> list[etree._Element]:
    """Visible runs of a paragraph in order (excludes deleted text and text boxes).

    For an editable paragraph these are exactly its direct ``w:r`` children.
    """
    return list(_RUN_XPATH(p))


def run_text(r: etree._Element) -> str:
    parts: list[str] = []
    for child in r:
        name = local(child)
        if name == "t":
            parts.append(child.text or "")
        elif name in ("tab", "ptab"):
            parts.append("\t")
        elif name in ("br", "cr"):
            parts.append("\n")
        elif name == "noBreakHyphen":
            parts.append("‑")
        elif name == "softHyphen":
            parts.append("­")
    return "".join(parts)


def textbox_texts(p: etree._Element) -> list[str]:
    """Text of each (outermost) text box anchored in this paragraph."""
    texts = []
    for box in _TEXTBOX_XPATH(p):
        lines = ["".join(run_text(r) for r in _BOXED_RUN_XPATH(bp)) for bp in box.iter(w("p"))]
        text = "\n".join(line for line in lines if line.strip())
        if text:
            texts.append(text)
    return texts


# --------------------------------------------------------------------------
# Editability
# --------------------------------------------------------------------------


def _run_reason(r: etree._Element) -> str | None:
    for child in r:
        name = local(child)
        if child.tag == f"{{{MC_NS}}}AlternateContent" or name in ("drawing", "pict"):
            return "text_box" if _TEXTBOX_XPATH(child) or child.find(".//{*}textbox") is not None \
                else "drawing"
        if name in _RUN_CHILD_REASONS:
            return _RUN_CHILD_REASONS[name]
        if name == "rPr" and child.find(w("rPrChange")) is not None:
            return "tracked_change"
        if name == "br" and wattr(child, "type") in ("page", "column"):
            return "page_break"
        if child.tag != w(name) or name not in _TEXT_RUN_CHILDREN:
            return "unsupported_markup"
    return None


def _ppr_reason(ppr: etree._Element) -> str | None:
    if ppr.find(w("pPrChange")) is not None:
        return "tracked_change"
    mark = ppr.find(w("rPr"))
    if mark is not None and any(
        mark.find(w(tag)) is not None for tag in ("ins", "del", "moveFrom", "moveTo", "rPrChange")
    ):
        return "tracked_change"
    return None


def non_editable_reason(ref: ParagraphRef) -> str | None:
    """Why a paragraph cannot be rewritten in place, or None if it can."""
    if ref.locked:
        return "content_control"
    for child in ref.element:
        name = local(child)
        if child.tag == w("r"):
            reason = _run_reason(child)
        elif child.tag == w("pPr"):
            reason = _ppr_reason(child)
        elif child.tag == w(name) and name in _PASSIVE_PARAGRAPH_CHILDREN:
            reason = None
        elif isinstance(child.tag, str):
            reason = _PARAGRAPH_CHILD_REASONS.get(name, "unsupported_markup")
            if child.tag != w(name):
                reason = "text_box" if _TEXTBOX_XPATH(child) else "unsupported_markup"
        else:
            reason = None  # comments / processing instructions
        if reason:
            return reason
    return None


_KEEP_EXTERNAL = ("/hyperlink",)


def strip_external_relationships(data: bytes) -> bytes:
    """`data` without relationships that make a renderer fetch something: linked images,
    OLE objects, attached templates and sub-documents with TargetMode="External". A
    converter follows those (file:// and http:// alike), which would read local files or
    reach internal hosts on behalf of whoever uploaded the document. Hyperlinks are kept;
    they are only followed by a person. Returns `data` itself when nothing had to go."""
    try:
        source = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise InvalidDocument("not a DOCX (zip) file") from exc
    replaced: dict[str, bytes] = {}
    for info in source.infolist():
        if not info.filename.endswith(".rels") or info.file_size > MAX_PART_BYTES:
            continue
        root = parse_xml(source.read(info.filename))
        doomed = [
            rel for rel in root.iter(f"{{{PKG_REL_NS}}}Relationship")
            if rel.get("TargetMode", "").lower() == "external"
            and not rel.get("Type", "").endswith(_KEEP_EXTERNAL)
        ]
        if doomed:
            for rel in doomed:
                rel.getparent().remove(rel)
            replaced[info.filename] = etree.tostring(root, encoding="UTF-8", xml_declaration=True,
                                                     standalone=True)
    if not replaced:
        return data
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.file_size > MAX_PART_BYTES:
                raise InvalidDocument(f"part {info.filename} exceeds {MAX_PART_BYTES} bytes")
            target.writestr(info.filename, replaced.get(info.filename) or source.read(info.filename))
    return out.getvalue()
