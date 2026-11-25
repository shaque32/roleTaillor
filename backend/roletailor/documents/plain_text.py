"""Plain-text (pasted) resume reader."""

from __future__ import annotations

import re

from ._analysis import looks_like_heading, missing_section_findings, strip_bullet
from .model import Block, ParsedDocument

_CONTINUATION_ENDINGS = (",", ";", "-", "–", "/", "&", "(")
_SENTENCE_ENDINGS = (".", "!", "?", ":")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_BLANKS = re.compile(r"[ \t ]+")
_NUMBERING = re.compile(r"^\d{1,2}[.)]\s+")


def _clean_lines(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    return [_BLANKS.sub(" ", line).strip() for line in text.split("\n")]


def _split_bullet(line: str) -> tuple[str, bool]:
    text, is_list = strip_bullet(line)
    if is_list:
        return text.strip(), True
    match = _NUMBERING.match(line)
    return (line[match.end():].strip(), True) if match else (line, False)


def _is_heading(text: str) -> bool:
    return looks_like_heading(text, all_bold=False)


def _continues(previous: str, line: str, *, previous_is_heading: bool) -> bool:
    """Whether `line` is a visual wrap of `previous` rather than a new paragraph."""
    if previous_is_heading or _split_bullet(line)[1] or _is_heading(line):
        return False
    if previous.endswith(_CONTINUATION_ENDINGS):
        return True
    # Lowercase starts are wraps, except contact lines (email, URL) under a name.
    contact = "@" in line or line.startswith(("http", "www."))
    return line[0].islower() and not contact and not previous.endswith(_SENTENCE_ENDINGS)


def read_plain_text(text: str) -> ParsedDocument:
    """Parse pasted resume text into `text_line` blocks (`t0`, `t1`, ...)."""
    paragraphs: list[tuple[str, bool]] = []
    previous_raw = ""
    for line in _clean_lines(text):
        if not line:
            previous_raw = ""
            continue
        if previous_raw and paragraphs and _continues(
                previous_raw, line, previous_is_heading=_is_heading(paragraphs[-1][0])):
            merged, is_list = paragraphs[-1]
            paragraphs[-1] = (f"{merged} {line}", is_list)
        else:
            body, is_list = _split_bullet(line)
            if not body:
                previous_raw = ""
                continue
            paragraphs.append((body, is_list))
        previous_raw = line

    blocks = [
        Block(
            id=f"t{n}", kind="text_line", text=body, is_list_item=is_list,
            is_heading=not is_list and looks_like_heading(
                body, all_bold=False, allow_caps_only=n > 0),
        )
        for n, (body, is_list) in enumerate(paragraphs)
    ]
    findings = missing_section_findings(blocks) if blocks else [
        {"code": "empty_text", "detail": "No text was found in the pasted resume"}]
    return ParsedDocument(
        source_format="text",
        blocks=blocks,
        layout_metadata={
            "source": "paste", "line_count": len(blocks),
            "char_count": sum(len(b.text) for b in blocks),
        },
        findings=findings,
        supports_in_place_edit=False,
    )
