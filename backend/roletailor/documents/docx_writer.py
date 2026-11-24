"""Apply block-keyed text edits to a DOCX at the XML level, preserving formatting.

Only the main document part is re-serialized, and only edited paragraphs change; every
other zip entry (styles, numbering, headers/footers, media) is copied byte-for-byte.
"""

from __future__ import annotations

import copy
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO

from lxml import etree

from ._ooxml import (
    XML_SPACE,
    DocxPackage,
    ParagraphRef,
    body_of,
    iter_paragraphs,
    non_editable_reason,
    parse_xml,
    run_text,
    serialize_like,
    w,
)
from .model import EditRejected

# Characters XML 1.0 cannot carry (besides \t and \n, which map to w:tab / w:br).
_INVALID_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")
_SEGMENTS = re.compile(r"(\t|\n)")
# Run-property children that describe revisions and must not be cloned onto new runs.
_REVISION_RPR = frozenset({"ins", "del", "moveFrom", "moveTo", "rPrChange"})


@dataclass(frozen=True)
class _Span:
    run: etree._Element
    start: int
    end: int
    text: str


def apply_block_edits(data: bytes, edits: dict[str, str]) -> bytes:
    """Return a new DOCX with each block's text replaced by `edits[block_id]`.

    All edits are validated before anything changes: an unknown id, a non-editable block
    or text XML cannot represent raises `EditRejected` and nothing is applied. With no
    effective edits the input bytes are returned unchanged.
    """
    pkg = DocxPackage(data)
    raw = pkg.read(pkg.main_part) or b""
    document = parse_xml(raw)
    targets = _resolve_targets(body_of(document), edits)

    changed = False
    for block_id, new_text in edits.items():
        changed |= _rewrite_paragraph(targets[block_id].element, _normalize_text(new_text))
    if not changed:
        return data
    return _repackage(pkg, {pkg.main_part: serialize_like(raw, document)})


def _resolve_targets(body: etree._Element, edits: dict[str, str]) -> dict[str, ParagraphRef]:
    refs = {ref.block_id: ref for ref in iter_paragraphs(body)}
    targets: dict[str, ParagraphRef] = {}
    for block_id, new_text in edits.items():
        ref = refs.get(block_id)
        if ref is None:
            raise EditRejected(f"unknown block id {block_id!r}")
        if reason := non_editable_reason(ref):
            raise EditRejected(f"block {block_id!r} is not editable ({reason})")
        if not isinstance(new_text, str):
            raise EditRejected(f"edit for {block_id!r} must be a string")
        if _INVALID_XML_CHARS.search(new_text):
            raise EditRejected(f"edit for {block_id!r} contains control characters")
        targets[block_id] = ref
    return targets


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


# --------------------------------------------------------------------------
# Run surgery
# --------------------------------------------------------------------------


def _spans(p: etree._Element) -> list[_Span]:
    spans, pos = [], 0
    for run in p.iterchildren(w("r")):
        text = run_text(run)
        spans.append(_Span(run, pos, pos + len(text), text))
        pos += len(text)
    return spans


def _common_prefix(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _rewrite_paragraph(p: etree._Element, new: str) -> bool:
    """Replace the paragraph's text with `new`, keeping run formatting where possible.

    The common prefix and suffix of old/new text stay in their original runs. The changed
    middle goes into the first run overlapping the changed region (inheriting its rPr);
    the other overlapping runs keep only their unchanged tail, or are removed when empty.
    A pure insertion goes into the run holding the character right after the insertion
    point (or the last run when appending), so text typed after a bold "Label:" run
    lands in the following plain run. Returns False when the text is unchanged.
    """
    spans = _spans(p)
    old = "".join(s.text for s in spans)
    if old == new:
        return False
    texted = [s for s in spans if s.text]
    if not texted:
        _set_run_text(_new_run(p), new)
        return True

    start = _common_prefix(old, new)
    suffix = _common_prefix(old[start:][::-1], new[start:][::-1])
    old_end, middle = len(old) - suffix, new[start:len(new) - suffix]

    touched = [s for s in texted if s.start < old_end and s.end > start]
    if not touched:
        anchor = next((s for s in texted if s.start <= start < s.end), texted[-1])
        cut = start - anchor.start
        _set_run_text(anchor.run, anchor.text[:cut] + middle + anchor.text[cut:])
        return True

    first, last = touched[0], touched[-1]
    head = first.text[: start - first.start]
    tail = last.text[old_end - last.start:]
    if first is last:
        _set_or_remove(first.run, head + middle + tail)
        return True
    _set_or_remove(first.run, head + middle)
    for span in touched[1:-1]:
        _remove(span.run)
    _set_or_remove(last.run, tail)
    return True


def _set_or_remove(run: etree._Element, text: str) -> None:
    if text:
        _set_run_text(run, text)
    else:
        _remove(run)


def _remove(el: etree._Element) -> None:
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


def _set_run_text(run: etree._Element, text: str) -> None:
    """Replace a run's content (keeping its rPr) with w:t / w:tab / w:br for `text`."""
    for child in list(run):
        if child.tag != w("rPr"):
            run.remove(child)
    for segment in _SEGMENTS.split(text):
        if not segment:
            continue
        if segment == "\t":
            etree.SubElement(run, w("tab"))
        elif segment == "\n":
            etree.SubElement(run, w("br"))
        else:
            t = etree.SubElement(run, w("t"))
            t.text = segment
            if segment != segment.strip() or "  " in segment:
                t.set(XML_SPACE, "preserve")


def _new_run(p: etree._Element) -> etree._Element:
    """Append a run formatted like the paragraph mark (what Word does when typing into
    an empty paragraph)."""
    run = etree.SubElement(p, w("r"))
    mark = p.find(f"{w('pPr')}/{w('rPr')}")
    if mark is not None:
        rpr = copy.deepcopy(mark)
        for child in list(rpr):
            if etree.QName(child).localname in _REVISION_RPR:
                rpr.remove(child)
        run.insert(0, rpr)
    return run


# --------------------------------------------------------------------------
# Packaging
# --------------------------------------------------------------------------


def _repackage(pkg: DocxPackage, replacements: dict[str, bytes]) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w") as dest:
        for info in pkg.zip.infolist():
            payload = replacements.get(info.filename)
            if payload is None:
                payload = pkg.zip.read(info.filename)
            dest.writestr(info, payload, compress_type=info.compress_type)
    return out.getvalue()
