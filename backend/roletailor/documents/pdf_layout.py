"""Geometric PDF reader: the single source of truth for PDF block ids.

`pdf_paragraphs` turns a text PDF into the same `l{n}` paragraphs the AI pipeline sees, but keeps the
source lines (position, font, size, colour, fragments) of every paragraph. The in-place writer
(`pdf_writer`) maps a block id back to geometry through this module, so the reader and the writer can
never disagree about which text a block id names.

Coordinates are PDF user space (origin bottom-left, y up). Only upright text is read.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from io import BytesIO

import pdfplumber

from ._analysis import BULLET_CHARS, looks_like_heading, strip_bullet
from .errors import InvalidDocument

# Chars whose baselines differ by less than this fraction of the font size share a line.
BASELINE_TOLERANCE = 0.3
# A horizontal gap wider than this fraction of the font size is a word space.
SPACE_GAP = 0.25
# A gap wider than this many ems (tab stop, right-aligned date, second column) splits a fragment.
FRAGMENT_GAP = 1.5
# A baseline jump larger than this many ems ends a paragraph even if the lines would otherwise wrap.
PARAGRAPH_GAP = 2.3
# Approximate descent below the baseline, in ems, used to derive a line's vertical extent.
_DESCENT = 0.27
# A column's fragments start within this many points of each other, on at least this many rows,
# and (unlike right-aligned dates) end at varying x.
COLUMN_X_TOL = 1.5
COLUMN_MIN_ROWS = 4
COLUMN_MIN_X1_SPREAD = 3.0
# A line at least this fraction of the page's longest line is treated as wrapped prose.
_FULL_LINE_RATIO = 0.8
_CONTINUATION_ENDINGS = (",", ";", "-", "–", "/", "&", "(")
_SENTENCE_ENDINGS = (".", "!", "?", ":")
# A short "Label:" opener ("Languages: Python, SQL") starts its own item, never a wrap.
_ENDS_WITH_YEAR = re.compile(r"(?:\d{4}|[Pp]resent|[Nn]ow)$")
_LABEL_LINE = re.compile(r"^[A-Z][\w&/+.\- ]{0,28}:\s")

# (font name, size, fill colour) of a run of glyphs.
Style = tuple[str, float, tuple[float, ...]]


@dataclass(frozen=True)
class Run:
    """A stretch of one style inside a fragment, starting at text offset `offset` and `x0`."""

    offset: int
    x0: float
    style: Style


@dataclass(frozen=True)
class Fragment:
    """A run of a line separated from its neighbours by a large gap (tab, right-aligned date)."""

    text: str
    x0: float
    x1: float
    runs: tuple[Run, ...]  # style runs in order; a bold label followed by plain text has two

    @property
    def style(self) -> Style:
        """Style of the last run: the one an edit confined to the fragment's tail is drawn in."""
        return self.runs[-1].style

    @property
    def mixed(self) -> bool:
        return len(self.runs) > 1


@dataclass(frozen=True)
class Line:
    """One visual text line. `x0`/`x1` bound the text after the bullet glyph, if any."""

    page: int
    text: str  # raw text including the bullet glyph prefix, as the paragraph merger sees it
    x0: float
    x1: float
    top: float
    bottom: float
    baseline: float
    font: str
    size: float
    color: tuple[float, ...]
    fragments: tuple[Fragment, ...]
    bullet: str | None = None
    bullet_x0: float | None = None
    bullet_x1: float | None = None
    bullet_style: Style | None = None
    # Horizontal extent of the column flow the line belongs to (None: the page's own margins).
    limit_left: float | None = None
    limit_right: float | None = None

    @property
    def flow(self) -> tuple[float | None, float | None]:
        return (self.limit_left, self.limit_right)

    @property
    def body(self) -> str:
        """Text without the bullet glyph (fragments joined by single spaces)."""
        return " ".join(f.text for f in self.fragments)

    @property
    def style(self) -> Style:
        return (self.font, self.size, self.color)


@dataclass(frozen=True)
class Paragraph:
    """A block as the reader assigns it: id, text, list flag, bullet glyph and source lines."""

    id: str
    text: str
    is_list_item: bool
    bullet: str | None
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class _Glyph:
    text: str
    x0: float
    x1: float
    baseline: float
    style: Style
    space_before: bool = False


def open_plumber(data: bytes) -> pdfplumber.PDF:
    try:
        return pdfplumber.open(BytesIO(data))
    except Exception as exc:  # pdfminer raises a wide range of syntax errors
        raise InvalidDocument(f"not a readable PDF: {exc}") from exc


def pages_without_text(data: bytes) -> list[int]:
    """Indexes of pages with no extractable (non-whitespace) characters, e.g. scanned pages."""
    with open_plumber(data) as pdf:
        return [
            index for index, page in enumerate(pdf.pages)
            if not any(c["text"].strip() for c in page.chars)
        ]


def read_lines(data: bytes) -> list[Line]:
    """All text lines of the document in reading order (page by page, top to bottom)."""
    lines: list[Line] = []
    with open_plumber(data) as pdf:
        for index, page in enumerate(pdf.pages):
            lines.extend(_page_lines(index, page.chars))
    return lines


def pdf_paragraphs(data: bytes) -> list[Paragraph]:
    """Paragraphs (blocks) of the document with ids `l0`, `l1`, ... in reading order."""
    return paragraphs_from_lines(read_lines(data))


def paragraphs_from_lines(lines: list[Line]) -> list[Paragraph]:
    """Group lines into paragraphs page by page and number them document-wide."""
    paragraphs: list[Paragraph] = []
    for page in sorted({line.page for line in lines}):
        for group in merge_lines([line for line in lines if line.page == page]):
            first = group[0]
            body, is_list = strip_bullet(first.text)
            text = " ".join([body, *(line.text for line in group[1:])])
            paragraphs.append(Paragraph(
                id=f"l{len(paragraphs)}", text=text, is_list_item=is_list,
                bullet=first.bullet if is_list else None, lines=tuple(group)))
    return paragraphs


def paragraph_is_heading(paragraph: Paragraph) -> bool:
    """Heading heuristic used by the reader (an all-caps first line is the candidate's name)."""
    return not paragraph.is_list_item and looks_like_heading(
        paragraph.text, all_bold=False, allow_caps_only=paragraph.id != "l0")


# --- paragraph merging -------------------------------------------------------------------------


def continues(previous: str, line: str, full_width: int) -> bool:
    """Whether `line` is a visual wrap of `previous` rather than a new paragraph."""
    if not line or strip_bullet(line)[1] or looks_like_heading(line, all_bold=False):
        return False
    if _LABEL_LINE.match(line):
        return False
    if previous.endswith(_CONTINUATION_ENDINGS) or line[0].islower():
        return True
    return len(previous) >= _FULL_LINE_RATIO * full_width and not previous.endswith(
        _SENTENCE_ENDINGS)


def merge_lines(lines: list[Line]) -> list[list[Line]]:
    """Group one page's lines into paragraphs; a large vertical gap splits paragraphs."""
    full_width = max((len(line.text) for line in lines), default=0)
    merged: list[list[Line]] = []
    previous: Line | None = None
    for line in lines:
        if previous is not None and (
                _gap_ems(previous, line) > PARAGRAPH_GAP or previous.flow != line.flow
                or line.baseline > previous.baseline + 0.5 * line.size):  # another column, or back up the page
            previous = None
        if previous is not None and merged and not looks_like_heading(
                _joined(merged[-1]), all_bold=False) and continues(previous.text, line.text, full_width):
            merged[-1].append(line)
        else:
            merged.append([line])
        previous = line
    return merged


def _joined(group: list[Line]) -> str:
    return " ".join([strip_bullet(group[0].text)[0], *(line.text for line in group[1:])])


def _gap_ems(upper: Line, lower: Line) -> float:
    return (upper.baseline - lower.baseline) / max(upper.size, lower.size, 1.0)


# --- line building -----------------------------------------------------------------------------


def _page_lines(page_index: int, chars: list[dict]) -> list[Line]:
    glyphs = _glyphs(chars)
    glyphs.sort(key=lambda g: (-g.baseline, g.x0))
    rows: list[list[_Glyph]] = []
    for glyph in glyphs:
        if rows and abs(rows[-1][0].baseline - glyph.baseline) <= BASELINE_TOLERANCE * glyph.style[1]:
            rows[-1].append(glyph)
        else:
            rows.append([glyph])
    rows = [sorted(row, key=lambda g: g.x0) for row in rows]
    spans = _column_spans(rows)
    if not spans:
        return [line for line in (_build_line(page_index, row) for row in rows) if line is not None]
    return _column_lines(page_index, rows, spans)


# --- column flows --------------------------------------------------------------------------------


def _gap_groups(row: list[_Glyph]) -> list[list[_Glyph]]:
    """Split a row at large gaps; a lone bullet glyph stays with the text it introduces."""
    groups: list[list[_Glyph]] = [[row[0]]]
    for previous, glyph in zip(row, row[1:], strict=False):
        if glyph.x0 - previous.x1 > FRAGMENT_GAP * max(previous.style[1], glyph.style[1]):
            groups.append([glyph])
        else:
            groups[-1].append(glyph)
    merged: list[list[_Glyph]] = []
    for group in groups:
        if merged and len(merged[-1]) == 1 and merged[-1][0].text in BULLET_CHARS:
            merged[-1].extend(group)
        else:
            merged.append(group)
    return merged


def _column_spans(rows: list[list[_Glyph]]) -> list[tuple[float, int, int]]:
    """Detected column starts as (x, first row, last row), rows being indexes into `rows`.

    A column's fragments start at one x on several rows and end at varying x; right-aligned dates
    also share a start only by accident but always share their right edge, so they never qualify.
    """
    candidates: list[tuple[float, float, int]] = []  # (x0, x1, row) of every non-first fragment
    for index, row in enumerate(rows):
        for group in _gap_groups(row)[1:]:
            candidates.append((group[0].x0, group[-1].x1, index))
    candidates.sort()
    spans: list[tuple[float, int, int]] = []
    cluster: list[tuple[float, float, int]] = []
    for candidate in [*candidates, None]:
        if cluster and (candidate is None or candidate[0] - cluster[0][0] > COLUMN_X_TOL):
            members = {row for _, _, row in cluster}
            x1s = [x1 for _, x1, _ in cluster]
            if len(members) >= COLUMN_MIN_ROWS and max(x1s) - min(x1s) > COLUMN_MIN_X1_SPREAD \
                    and not _is_label_table(rows, members):
                start = min(x0 for x0, _, _ in cluster)
                spans.append((start, *_extend(rows, start, min(members), max(members))))
            cluster = []
        if candidate is not None:
            cluster.append(candidate)
    return spans


def _is_label_table(rows: list[list[_Glyph]], members: set[int]) -> bool:
    """Whether the rows pair a label or date with its value ("Languages:   Python, SQL",
    "2019 - 2021   Acme"). Such rows read across, so they must stay one line each."""
    lefts = ["".join(g.text for g in _gap_groups(rows[index])[0]).strip() for index in members]
    paired = sum(1 for text in lefts if text.endswith(":") or _ENDS_WITH_YEAR.search(text))
    return 2 * paired >= len(lefts)


def _extend(rows: list[list[_Glyph]], start: float, top: int, bottom: int) -> tuple[int, int]:
    """Grow a column's row range over adjacent rows that lie wholly at or after the column start."""
    def at_start(index: int) -> bool:
        return abs(rows[index][0].x0 - start) <= COLUMN_X_TOL

    while top > 0 and at_start(top - 1):
        top -= 1
    while bottom + 1 < len(rows) and at_start(bottom + 1):
        bottom += 1
    return top, bottom


def _column_lines(page_index: int, rows: list[list[_Glyph]], spans: list[tuple[float, int, int]]) -> list[Line]:
    """Lines in reading order: rows outside a column band as usual; inside, one flow after the other."""
    spans = sorted(spans)
    starts = [x for x, _, _ in spans]
    bands: list[list[int]] = []  # [first row, last row] of every run of overlapping column spans
    for _, first, last in sorted(spans, key=lambda span: span[1]):
        if bands and first <= bands[-1][1] + 1:
            bands[-1][1] = max(bands[-1][1], last)
        else:
            bands.append([first, last])

    def flow_of(glyph: _Glyph, index: int) -> int:
        return sum(1 for x, first, last in spans if first <= index <= last and glyph.x0 >= x - COLUMN_X_TOL)

    lines: list[Line] = []
    row_index = 0
    for first, last in bands:
        for index in range(row_index, first):
            lines.extend(_row_lines(page_index, rows[index], [0] * len(rows[index])))
        pieces: list[tuple[int, Line]] = []
        for index in range(first, last + 1):
            flows = [flow_of(g, index) for g in rows[index]]
            pieces.extend(_row_pieces(page_index, rows[index], flows))
        lines.extend(_with_limits(pieces, starts))
        row_index = last + 1
    for index in range(row_index, len(rows)):
        lines.extend(_row_lines(page_index, rows[index], [0] * len(rows[index])))
    return lines


def _row_pieces(page_index: int, row: list[_Glyph], flows: list[int]) -> list[tuple[int, Line]]:
    pieces: list[tuple[int, Line]] = []
    for flow in sorted(set(flows)):
        line = _build_line(page_index, [g for g, f in zip(row, flows, strict=True) if f == flow])
        if line is not None:
            pieces.append((flow, line))
    return pieces


def _row_lines(page_index: int, row: list[_Glyph], flows: list[int]) -> list[Line]:
    return [line for _, line in _row_pieces(page_index, row, flows)]


def _with_limits(pieces: list[tuple[int, Line]], starts: list[float]) -> list[Line]:
    """Order a band's pieces flow by flow and tell each its column's horizontal limits."""
    right: dict[int, float] = {}
    for flow, line in pieces:
        right[flow] = max(right.get(flow, line.x1), line.x1)
    last = max(right)
    ordered = sorted(enumerate(pieces), key=lambda item: (item[1][0], item[0]))
    return [
        replace(line, limit_left=starts[flow - 1] if flow else None, limit_right=right[flow] if flow < last else None)
        for _, (flow, line) in ordered
    ]


def _glyphs(chars: list[dict]) -> list[_Glyph]:
    """Convert pdfplumber chars to glyphs; whitespace chars become a `space_before` flag."""
    ordered = sorted(
        (c for c in chars if c.get("upright", True)),
        key=lambda c: (-round(c["matrix"][5], 1), c["matrix"][4]))
    glyphs: list[_Glyph] = []
    pending_space = False
    last_baseline: float | None = None
    for c in ordered:
        baseline = c["matrix"][5]
        if last_baseline is None or abs(baseline - last_baseline) > BASELINE_TOLERANCE * c["size"]:
            pending_space = False
        last_baseline = baseline
        if not c["text"] or c["text"].isspace():
            pending_space = True
            continue
        x0 = c["matrix"][4]
        glyph = _Glyph(
            text=c["text"], x0=x0, x1=x0 + (c["x1"] - c["x0"]), baseline=baseline,
            style=(c["fontname"], round(float(c["size"]), 2), _color(c.get("non_stroking_color"))),
            space_before=pending_space)
        pending_space = False
        if glyphs and _duplicates(glyphs[-1], glyph):  # faux-bold double strike
            continue
        glyphs.append(glyph)
    return glyphs


def _duplicates(a: _Glyph, b: _Glyph) -> bool:
    return a.text == b.text and abs(a.x0 - b.x0) < 0.01 * a.style[1] and abs(a.baseline - b.baseline) < 0.1


def _color(value: object) -> tuple[float, ...]:
    if isinstance(value, (tuple, list)) and all(isinstance(v, (int, float)) for v in value):
        return tuple(round(float(v), 4) for v in value) or (0.0,)
    return (0.0,)


def _build_line(page_index: int, row: list[_Glyph]) -> Line | None:
    if not row:
        return None
    bullet, body = _split_bullet(row)
    if not body:
        body, bullet = row, None
    fragments = _fragments(body)
    style, _ = Counter(g.style for g in body).most_common(1)[0]
    baseline = body[0].baseline
    bottom = baseline - _DESCENT * style[1]
    text = " ".join(f.text for f in fragments)
    return Line(
        page=page_index, text=f"{bullet.text} {text}" if bullet else text,
        x0=body[0].x0, x1=body[-1].x1, top=bottom + style[1], bottom=bottom, baseline=baseline,
        font=style[0], size=style[1], color=style[2], fragments=tuple(fragments),
        bullet=bullet.text if bullet else None, bullet_x0=bullet.x0 if bullet else None,
        bullet_x1=bullet.x1 if bullet else None, bullet_style=bullet.style if bullet else None)


def _split_bullet(row: list[_Glyph]) -> tuple[_Glyph | None, list[_Glyph]]:
    """Split a leading bullet glyph (followed by a space or gap) from the line's text."""
    first = row[0]
    if len(row) < 2 or first.text not in BULLET_CHARS:
        return None, row
    following = row[1]
    if following.space_before or following.x0 - first.x1 > SPACE_GAP * first.style[1]:
        return first, [replace(following, space_before=False), *row[2:]]
    return None, row


def _fragments(glyphs: list[_Glyph]) -> list[Fragment]:
    """Split a line's glyphs at large gaps into fragments, tracking text offsets of style runs."""
    groups: list[list[tuple[_Glyph, int]]] = [[]]
    texts: list[list[str]] = [[]]
    length = 0
    for previous, glyph in zip([None, *glyphs], glyphs, strict=False):
        if previous is not None:
            gap = glyph.x0 - previous.x1
            size = max(previous.style[1], glyph.style[1])
            if gap > FRAGMENT_GAP * size:
                groups.append([])
                texts.append([])
                length = 0
            elif glyph.space_before or gap > SPACE_GAP * size:
                texts[-1].append(" ")
                length += 1
        groups[-1].append((glyph, length))
        texts[-1].append(glyph.text)
        length += len(glyph.text)
    return [_fragment(group, "".join(parts)) for group, parts in zip(groups, texts, strict=True)]


def _fragment(group: list[tuple[_Glyph, int]], text: str) -> Fragment:
    """Build a fragment; a run that follows a word space owns that space (it is drawn with the run)."""
    runs: list[Run] = []
    for i, (glyph, offset) in enumerate(group):
        if runs and runs[-1].style == glyph.style:
            continue
        x0 = glyph.x0
        if i and offset and text[offset - 1] == " ":
            offset, x0 = offset - 1, group[i - 1][0].x1
        runs.append(Run(offset=offset, x0=x0, style=glyph.style))
    return Fragment(text=text, x0=group[0][0].x0, x1=group[-1][0].x1, runs=tuple(runs))
