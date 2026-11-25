"""Edit a text PDF in place: remove the old text operators, draw the new text, verify the result.

`edit_pdf_in_place` is all-or-nothing like `apply_block_edits` for DOCX: every edit is planned
(geometry, font, reflow) before a single byte of output exists, and anything that cannot be done
faithfully raises `PdfInPlaceUnsupported` so the caller can fall back to the ATS template renderer.

Why the old text is deleted rather than covered by a white box: ATS parsers read the content
stream, so covered text would still be extracted next to the new text. Why the new text is inserted
right after the original `ET` instead of appended to the page: stream order is reading order for
many parsers, and a tailored bullet should stay between its neighbours.

Block ids come from `pdf_layout.pdf_paragraphs`, the same function the reader uses, and the output
is re-read with it as a safety net: any block that changed unexpectedly aborts the edit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import pikepdf

from .errors import InvalidDocument, PdfInPlaceUnsupported
from .model import EditRejected
from .pdf_content import ShowEvent, invert, removal_replacement, walk
from .pdf_fonts import (
    FontCodec,
    PdfFont,
    SubstituteFont,
    embed_substitute,
    load_pdf_font,
    resolve_font_file,
    strip_subset_prefix,
    substitute_style,
)
from .pdf_layout import Fragment, Line, Paragraph, pdf_paragraphs

# Font sizes tried, as fractions of the original, before giving up on fitting the new text.
SHRINK_STEPS = (1.0, 0.98, 0.96, 0.94, 0.92, 0.90)
_BASELINE_TOL = 0.3  # of font size, matches the reader's line clustering
_X_TOL = 1.0  # points; show operators this close outside a line still belong to it
_MIN_OVERLAP = 0.3  # of font size; less overlap than this is a shared space glyph, not text
_FRAGMENT_MARGIN = 0.5  # ems kept between an edited fragment and its neighbour
_ALIGN_TOL = 1.5  # points when detecting centred and right-aligned text


@dataclass(frozen=True)
class BlockEditReport:
    """How one block was edited."""

    block_id: str
    method: str  # "reuse_font" | "substitute_font"
    font_scale: float
    lines_before: int
    lines_after: int
    fragment_only: bool


@dataclass(frozen=True)
class PdfEditReport:
    """What `edit_pdf_in_place` did, one entry per effectively edited block."""

    blocks: tuple[BlockEditReport, ...] = ()

    def by_id(self) -> dict[str, BlockEditReport]:
        return {b.block_id: b for b in self.blocks}


# --- plan data ---------------------------------------------------------------------------------


@dataclass
class _FontRef:
    codec: FontCodec
    resource: str | None = None  # page resource name when reusing an existing font
    substitute: SubstituteFont | None = None

    @property
    def method(self) -> str:
        return "substitute_font" if self.substitute else "reuse_font"


@dataclass
class _Target:
    """A region of one baseline whose show operators are deleted."""

    baseline: float
    x_lo: float
    x_hi: float
    size: float
    bullet_x0: float | None = None  # set for the first line of a list item
    shared_bullet: bool = False
    removed: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class _Draw:
    text: str
    x: float
    baseline: float


@dataclass(frozen=True)
class _Bullet:
    text: str
    x: float
    baseline: float
    size: float
    color: tuple[float, ...]
    font: _FontRef


@dataclass
class _Plan:
    block_id: str
    page: int
    targets: list[_Target]
    draws: list[_Draw]
    font: _FontRef
    size: float
    color: tuple[float, ...]
    bullet: _Bullet | None
    report: BlockEditReport


class _Document:
    """Open PDF plus per-page caches shared by the planning steps."""

    def __init__(self, pdf: pikepdf.Pdf, paragraphs: list[Paragraph],
                 overrides: Mapping[str, str | Path] | None) -> None:
        self.pdf = pdf
        self.overrides = overrides
        self.substitutes: dict[Path, SubstituteFont] = {}
        self._bounds: dict[int, tuple[float, float]] = {}
        for par in paragraphs:
            for line in par.lines:
                left, right = self._bounds.get(line.page, (line.x0, line.x1))
                low = line.bullet_x0 if line.bullet_x0 is not None else line.x0
                self._bounds[line.page] = (min(left, low), max(right, line.x1))
        for page, (left, right) in list(self._bounds.items()):
            # A page of short lines says little about its margin: assume the right margin mirrors the left.
            box = [float(v) for v in pdf.pages[page].mediabox]
            self._bounds[page] = (left, max(right, box[2] - (left - box[0])))
        self._fonts: dict[int, list[tuple[str, PdfFont]]] = {}

    def bounds(self, page: int) -> tuple[float, float]:
        """Left and right edge of the page's text column (the right edge is at least the mirrored left margin)."""
        return self._bounds[page]

    def page_fonts(self, page: int) -> list[tuple[str, PdfFont]]:
        if page not in self._fonts:
            fonts = _resources(self.pdf.pages[page]).get("/Font")
            loaded = ((name, load_pdf_font(font)) for name, font in (fonts.items() if fonts is not None else []))
            self._fonts[page] = [(name, f) for name, f in loaded if f is not None]
        return self._fonts[page]

    def font_for(self, page: int, font_name: str, text: str, block_id: str) -> _FontRef:
        """Reuse the line's own font if it has every glyph, else a metric-compatible substitute."""
        base = strip_subset_prefix(font_name)
        for name, font in self.page_fonts(page):
            if font.base_name == base and font.can_encode(text):
                return _FontRef(font, resource=name)
        style = substitute_style(font_name)
        if style is None:
            raise PdfInPlaceUnsupported(
                f"font {base!r} lacks glyphs for the new text and has no metric-compatible substitute", block_id)
        path = resolve_font_file(style, self.overrides)
        if path is None:
            raise PdfInPlaceUnsupported(f"no installed font for {style.key}", block_id)
        substitute = self.substitutes.get(path) or SubstituteFont.open(path)
        if substitute is None:
            raise PdfInPlaceUnsupported(f"cannot use substitute font file {path}", block_id)
        if not substitute.can_encode(text):
            raise PdfInPlaceUnsupported(f"substitute font {style.key} lacks glyphs for the new text", block_id)
        self.substitutes[path] = substitute
        substitute.need(text)
        return _FontRef(substitute, substitute=substitute)

    def reuse_only(self, page: int, font_name: str, text: str) -> _FontRef | None:
        base = strip_subset_prefix(font_name)
        for name, font in self.page_fonts(page):
            if font.base_name == base and font.can_encode(text):
                return _FontRef(font, resource=name)
        return None


def _resources(page: pikepdf.Page) -> pikepdf.Dictionary:
    """The page's resource dictionary, following /Parent for inherited resources."""
    node = page.obj
    while node is not None:
        if "/Resources" in node:
            return node.Resources
        node = node.get("/Parent")
    page.obj.Resources = pikepdf.Dictionary()
    return page.obj.Resources


# --- public entry point ------------------------------------------------------------------------


def edit_pdf_in_place(
    data: bytes, edits: dict[str, str], *, font_overrides: Mapping[str, str | Path] | None = None,
) -> tuple[bytes, PdfEditReport]:
    """Return a PDF whose blocks have the text in `edits` (block id -> new text), edited in place.

    Raises `EditRejected` for unknown block ids and `PdfInPlaceUnsupported` when an edit cannot
    be made faithfully (no matching font, text does not fit, unusual structure, or the post-check
    finds any unintended change). With no effective edits the input bytes are returned unchanged.
    """
    paragraphs = pdf_paragraphs(data)
    by_id = {p.id: p for p in paragraphs}
    effective = _effective_edits(by_id, edits)
    if not effective:
        return data, PdfEditReport()
    try:
        pdf = pikepdf.open(BytesIO(data))
    except pikepdf.PdfError as exc:
        raise InvalidDocument(f"not a readable PDF: {exc}") from exc
    with pdf:
        doc = _Document(pdf, paragraphs, font_overrides)
        plans = [_plan_block(doc, by_id[bid], text) for bid, text in effective.items()]
        _embed_substitutes(doc, plans)
        for page in sorted({p.page for p in plans}):
            _rewrite_page(doc, page, [p for p in plans if p.page == page])
        out = BytesIO()
        pdf.save(out, deterministic_id=True)
    result = out.getvalue()
    _verify(paragraphs, effective, result, len(pdf.pages))
    return result, PdfEditReport(tuple(p.report for p in plans))


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _effective_edits(by_id: dict[str, Paragraph], edits: dict[str, str]) -> dict[str, str]:
    """Validate ids and types, normalise whitespace, and drop edits that change nothing."""
    effective: dict[str, str] = {}
    for block_id, new_text in edits.items():
        if block_id not in by_id:
            raise EditRejected(f"unknown block id {block_id!r}")
        if not isinstance(new_text, str):
            raise EditRejected(f"edit for {block_id!r} must be a string")
        text = _normalize(new_text)
        if text == by_id[block_id].text:
            continue
        if not text:
            raise PdfInPlaceUnsupported("emptying a block would shift later block ids", block_id)
        effective[block_id] = text
    order = {bid: n for n, bid in enumerate(by_id)}
    return dict(sorted(effective.items(), key=lambda kv: order[kv[0]]))


# --- planning ----------------------------------------------------------------------------------


def _plan_block(doc: _Document, par: Paragraph, new_text: str) -> _Plan:
    uniform = all(len(line.fragments) == 1 and not line.fragments[0].mixed for line in par.lines) \
        and len({line.style for line in par.lines}) == 1
    if uniform:
        return _plan_reflow(doc, par, new_text)
    if len(par.lines) == 1 or any(len(line.fragments) > 1 for line in par.lines):
        return _plan_fragment(doc, par, new_text)
    raise PdfInPlaceUnsupported("multi-line block mixes several fonts or styles", par.id)


def _anchor(x0: float, x1: float, left: float, right: float, has_bullet: bool) -> str:
    """Whether a single line looks left-aligned, centred or right-aligned within the text column."""
    if has_bullet or x0 <= left + 2 * _ALIGN_TOL:
        return "left"
    width = right - left
    if abs((x0 + x1) / 2 - (left + right) / 2) <= _ALIGN_TOL and x1 - x0 < 0.9 * width:
        return "center"
    if x1 >= right - _ALIGN_TOL and x1 - x0 < 0.6 * width:
        return "right"
    return "left"


def _plan_reflow(doc: _Document, par: Paragraph, new_text: str) -> _Plan:
    lines = par.lines
    first = lines[0]
    left, right = doc.bounds(first.page)
    anchor = "left"
    if len(lines) == 1:
        anchor = _anchor(first.x0, first.x1, left, right, first.bullet is not None)
        if anchor == "left":
            avail = [max(right, first.x1) - first.x0]
        elif anchor == "center":
            centre = (first.x0 + first.x1) / 2
            avail = [max(2 * min(centre - left, right - centre), first.x1 - first.x0)]
        else:
            avail = [max(first.x1 - left, first.x1 - first.x0)]
    else:
        centres = [(ln.x0 + ln.x1) / 2 for ln in lines]
        x0s = [ln.x0 for ln in lines]
        if max(centres) - min(centres) <= _ALIGN_TOL and max(x0s) - min(x0s) > 2 * _ALIGN_TOL:
            raise PdfInPlaceUnsupported("centred multi-line text is not supported", par.id)
        widest = max(ln.x1 for ln in lines)
        avail = [widest - ln.x0 for ln in lines]
    font = doc.font_for(first.page, first.font, new_text, par.id)
    wrapped, scale = _fit(font.codec, new_text, first.size, avail, par.id)
    size = first.size * scale
    draws = []
    for line, text in zip(lines, wrapped, strict=False):
        width = font.codec.width(text, size)
        if anchor == "center":
            x = (line.x0 + line.x1) / 2 - width / 2
        elif anchor == "right":
            x = line.x1 - width
        else:
            x = line.x0
        draws.append(_Draw(text, x, line.baseline))
    targets = [
        _Target(ln.baseline, ln.x0, ln.x1, ln.size, ln.bullet_x0 if n == 0 else None)
        for n, ln in enumerate(lines)
    ]
    report = BlockEditReport(par.id, font.method, scale, len(lines), len(wrapped), fragment_only=False)
    return _Plan(par.id, first.page, targets, draws, font, size, first.color,
                 _bullet(doc, first, par), report)


def _bullet(doc: _Document, line: Line, par: Paragraph) -> _Bullet | None:
    """How to redraw the bullet if it turns out to share a show operator with the text."""
    if par.bullet is None or line.bullet_style is None or line.bullet_x0 is None:
        return None
    ref = doc.reuse_only(line.page, line.bullet_style[0], par.bullet)
    if ref is None:
        return None
    return _Bullet(par.bullet, line.bullet_x0, line.baseline, line.bullet_style[1], line.bullet_style[2], ref)


def _fit(codec: FontCodec, text: str, size: float, avail: list[float], block_id: str) -> tuple[list[str], float]:
    """Greedy-wrap `text` into the slots, shrinking the font down to 90% if it does not fit."""
    words = text.split(" ")
    for scale in SHRINK_STEPS:
        wrapped = _wrap(codec, words, size * scale, avail)
        if wrapped is not None:
            return wrapped, scale
    raise PdfInPlaceUnsupported(
        f"new text does not fit in {len(avail)} line(s) even at {int(SHRINK_STEPS[-1] * 100)}% size", block_id)


def _wrap(codec: FontCodec, words: list[str], size: float, avail: list[float]) -> list[str] | None:
    lines: list[str] = []
    index = 0
    for width in avail:
        current = ""
        while index < len(words):
            candidate = f"{current} {words[index]}" if current else words[index]
            if codec.width(candidate, size) > width + 0.01:
                break
            current = candidate
            index += 1
        if not current:
            return None  # a single word is wider than the slot
        lines.append(current)
        if index == len(words):
            return lines
    return None


def _text_offsets(par: Paragraph) -> list[tuple[int, int, Fragment, Line]]:
    """(start, end, fragment, line) of every fragment inside the block text."""
    spans = []
    cursor = 0
    for line in par.lines:
        for fragment in line.fragments:
            spans.append((cursor, cursor + len(fragment.text), fragment, line))
            cursor += len(fragment.text) + 1
    return spans


def _plan_fragment(doc: _Document, par: Paragraph, new_text: str) -> _Plan:
    """Redraw only the tail of the one fragment containing the change, in its own box."""
    old = par.text
    prefix = 0
    limit = min(len(old), len(new_text))
    while prefix < limit and old[prefix] == new_text[prefix]:
        prefix += 1
    suffix = 0
    while suffix < limit - prefix and old[-1 - suffix] == new_text[-1 - suffix]:
        suffix += 1
    changed_end = len(old) - suffix
    for start, end, fragment, line in _text_offsets(par):  # noqa: B007 (loop vars are used after break)
        if start <= prefix and changed_end <= end:
            break
    else:
        raise PdfInPlaceUnsupported("the edit spans more than one fragment of the line", par.id)
    run = fragment.runs[-1]
    if prefix - start < run.offset:
        raise PdfInPlaceUnsupported("the edit touches a differently styled run of the line", par.id)
    new_fragment = new_text[start:len(new_text) - (len(old) - end)]
    tail = new_fragment[run.offset:]
    font_name, size, color = run.style
    font = doc.font_for(line.page, font_name, tail, par.id)

    left, right = doc.bounds(line.page)
    index = line.fragments.index(fragment)
    fits_left = line.fragments[index + 1].x0 - _FRAGMENT_MARGIN * size if index + 1 < len(line.fragments) else None
    anchor = "left"
    if len(line.fragments) == 1 and len(par.lines) == 1:
        anchor = _anchor(fragment.x0, fragment.x1, left, right, line.bullet is not None)
    elif index > 0 and index == len(line.fragments) - 1 and fragment.x1 >= right - _ALIGN_TOL:
        anchor = "right"
    if run.offset and anchor != "left":
        raise PdfInPlaceUnsupported("cannot re-align a line that mixes styles", par.id)
    if anchor == "right" and index > 0:
        low = line.fragments[index - 1].x1 + _FRAGMENT_MARGIN * size
        avail = fragment.x1 - low
    elif anchor == "right":
        avail = fragment.x1 - left
    elif anchor == "center":
        centre = (fragment.x0 + fragment.x1) / 2
        avail = max(2 * min(centre - left, right - centre), fragment.x1 - fragment.x0)
    else:
        avail = (fits_left if fits_left is not None else max(right, fragment.x1)) - run.x0
    avail = max(avail, fragment.x1 - run.x0)
    lead = tail[:len(tail) - len(tail.lstrip(" "))]  # the word space a run owns is drawn, not wrapped away
    (core,), scale = _fit(font.codec, tail[len(lead):], size, [avail - font.codec.width(lead, size)], par.id)
    wrapped = lead + core
    drawn_size = size * scale
    width = font.codec.width(wrapped, drawn_size)
    x = {"right": fragment.x1 - width, "center": (fragment.x0 + fragment.x1) / 2 - width / 2}.get(anchor, run.x0)
    leads = line is par.lines[0] and index == 0 and not run.offset  # the edit starts at the line's text start
    target = _Target(line.baseline, run.x0, fragment.x1, size, line.bullet_x0 if leads else None)
    report = BlockEditReport(par.id, font.method, scale, len(par.lines), len(par.lines), fragment_only=True)
    return _Plan(par.id, line.page, [target], [_Draw(wrapped, x, line.baseline)], font, drawn_size, color,
                 _bullet(doc, line, par) if leads else None, report)


def _embed_substitutes(doc: _Document, plans: list[_Plan]) -> None:
    """Embed each substitute font once and register it in every page that uses it."""
    objects: dict[Path, pikepdf.Object] = {}
    registered: dict[tuple[int, Path], str] = {}
    for plan in plans:
        sub = plan.font.substitute
        if sub is None:
            continue
        if sub.path not in objects:
            objects[sub.path] = embed_substitute(doc.pdf, sub)
        key = (plan.page, sub.path)
        if key not in registered:
            resources = _resources(doc.pdf.pages[plan.page])
            if "/Font" not in resources:
                resources.Font = pikepdf.Dictionary()
            number = len(registered)
            while f"/RTSub{number}" in resources.Font:
                number += 1
            registered[key] = f"/RTSub{number}"
            resources.Font[registered[key]] = objects[sub.path]
        plan.font.resource = registered[key]


# --- page rewriting ----------------------------------------------------------------------------


def _rewrite_page(doc: _Document, page_index: int, plans: list[_Plan]) -> None:
    page = doc.pdf.pages[page_index]
    try:
        instructions = list(pikepdf.parse_content_stream(page))
    except pikepdf.PdfError as exc:
        raise PdfInPlaceUnsupported(f"page {page_index} content stream is unreadable: {exc}") from exc
    result = walk(instructions, _resources(page))
    removals: dict[int, list] = {}
    for event in result.shows:
        _match_event(event, plans, removals)
    inserts: dict[int, list] = {}
    for plan in plans:
        removed = sorted(i for t in plan.targets for i in t.removed)
        if any(not t.removed for t in plan.targets) or not removed:
            raise PdfInPlaceUnsupported("could not locate the block's text in the page content", plan.block_id)
        anchor = next((i for i in range(removed[0], len(instructions))
                       if str(getattr(instructions[i], "operator", "")) == "ET"), None)
        if anchor is None or anchor not in result.ctm_at_et:
            raise PdfInPlaceUnsupported("text object of the block is not closed", plan.block_id)
        inserts.setdefault(anchor, []).extend(_draw_ops(plan, result.ctm_at_et[anchor]))
    rebuilt: list = []
    for index, instruction in enumerate(instructions):
        rebuilt.extend(removals.get(index, [instruction]))
        rebuilt.extend(inserts.get(index, []))
    page.obj.Contents = doc.pdf.make_stream(pikepdf.unparse_content_stream(rebuilt))


def _match_event(event: ShowEvent, plans: list[_Plan], removals: dict[int, list]) -> None:
    """Mark `event` for deletion if it draws part of a target line; reject straddling operators."""
    hit = False
    for plan in plans:
        for target in plan.targets:
            verdict = _classify(event, target, plan.block_id)
            if verdict == "skip":
                continue
            if event.in_form:
                raise PdfInPlaceUnsupported("the block's text is inside a Form XObject", plan.block_id)
            if event.advance is None:
                raise PdfInPlaceUnsupported("the font of the block's text cannot be measured", plan.block_id)
            target.removed.append(event.index)
            target.shared_bullet |= verdict == "bullet"
            hit = True
    if hit:
        removals[event.index] = removal_replacement(event)


def _classify(event: ShowEvent, target: _Target, block_id: str) -> str:
    """`skip`, `remove`, or `bullet` (operator also draws the bullet glyph); raises if it straddles."""
    if abs(event.start_y - target.baseline) > _BASELINE_TOL * target.size:
        return "skip"
    # An operator may begin or end with a space glyph, which the reader drops from the line's extent.
    low, high = target.x_lo - max(_X_TOL, 0.3 * target.size), target.x_hi + max(_X_TOL, 0.5 * target.size)
    if low <= event.start_x and event.end_x <= high:
        return "remove"
    overlap = min(event.end_x, target.x_hi) - max(event.start_x, target.x_lo)
    if overlap <= _MIN_OVERLAP * target.size:
        return "skip"
    if target.bullet_x0 is not None and target.bullet_x0 - _X_TOL <= event.start_x < low and event.end_x <= high:
        return "bullet"
    raise PdfInPlaceUnsupported("a text operator straddles the edited text and its neighbours", block_id)


def _color_ops(color: tuple[float, ...], block_id: str) -> pikepdf.ContentStreamInstruction:
    names = {1: "g", 3: "rg", 4: "k"}
    if len(color) not in names:
        raise PdfInPlaceUnsupported("unsupported fill colour space", block_id)
    return _ins(names[len(color)], *color)


def _ins(operator: str, *operands: object) -> pikepdf.ContentStreamInstruction:
    return pikepdf.ContentStreamInstruction(list(operands), pikepdf.Operator(operator))


def _draw_ops(plan: _Plan, ctm: tuple[float, ...]) -> list[pikepdf.ContentStreamInstruction]:
    """`q <undo CTM> BT ... ET Q` drawing the plan's lines in absolute user-space coordinates."""
    inverse = invert(ctm)  # type: ignore[arg-type]
    if inverse is None:
        raise PdfInPlaceUnsupported("degenerate transformation at the block's text", plan.block_id)
    ops = [_ins("q"), _ins("cm", *(round(v, 6) for v in inverse)), _ins("BT")]
    ops += [_ins("Tc", 0), _ins("Tw", 0), _ins("Tz", 100), _ins("Ts", 0), _ins("Tr", 0)]
    if plan.bullet is not None and any(t.shared_bullet for t in plan.targets):
        bullet = plan.bullet
        ops += [_color_ops(bullet.color, plan.block_id), _ins("Tf", pikepdf.Name(bullet.font.resource), bullet.size)]
        ops += _show(bullet.text, bullet.x, bullet.baseline, bullet.font.codec)
    elif any(t.shared_bullet for t in plan.targets):
        raise PdfInPlaceUnsupported("the bullet shares a text operator with the line and cannot be redrawn",
                                    plan.block_id)
    ops += [_color_ops(plan.color, plan.block_id), _ins("Tf", pikepdf.Name(plan.font.resource), round(plan.size, 4))]
    for draw in plan.draws:
        ops += _show(draw.text, draw.x, draw.baseline, plan.font.codec)
    return [*ops, _ins("ET"), _ins("Q")]


def _show(text: str, x: float, y: float, codec: FontCodec) -> list[pikepdf.ContentStreamInstruction]:
    return [_ins("Tm", 1, 0, 0, 1, round(x, 4), round(y, 4)), _ins("Tj", pikepdf.String(codec.encode(text)))]


# --- post-check --------------------------------------------------------------------------------


def _verify(before: list[Paragraph], edits: dict[str, str], output: bytes, page_count: int) -> None:
    """Re-read `output` with the same reader and abort unless only the edited blocks changed."""
    try:
        after = pdf_paragraphs(output)
        pages = len(pikepdf.open(BytesIO(output)).pages)
    except (InvalidDocument, pikepdf.PdfError) as exc:
        raise PdfInPlaceUnsupported(f"edited PDF is not readable: {exc}") from exc
    if pages != page_count:
        raise PdfInPlaceUnsupported("page count changed")
    if [p.id for p in after] != [p.id for p in before]:
        raise PdfInPlaceUnsupported("block structure changed after the edit")
    for old, new in zip(before, after, strict=True):
        expected = edits.get(old.id, old.text)
        if _normalize(new.text) != _normalize(expected):
            raise PdfInPlaceUnsupported("re-read text differs from the intended text", old.id)
        if (new.is_list_item, new.bullet) != (old.is_list_item, old.bullet):
            raise PdfInPlaceUnsupported("bullet changed", old.id)


__all__ = ["BlockEditReport", "PdfEditReport", "PdfInPlaceUnsupported", "edit_pdf_in_place"]


def fit_pdf_edits(data: bytes, edits: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Split `edits` into those that can be applied in place together and those that cannot.

    Returns `(kept, dropped)` where `dropped` maps block id to the reason. Blocks are laid
    out independently, so an edit that fails on its own (overflow, missing glyphs, mixed
    styles) is dropped and the rest retried. If the remaining edits only fail in
    combination, all of them are dropped. `edit_pdf_in_place(data, kept)` is then guaranteed
    to succeed, because the writer is deterministic. Unknown ids still raise `EditRejected`.
    """
    kept = dict(edits)
    dropped: dict[str, str] = {}
    while kept:
        try:
            edit_pdf_in_place(data, kept)
            break
        except PdfInPlaceUnsupported as exc:
            if exc.block_id in kept:
                failing = {exc.block_id: exc.reason}
            else:
                failing = _failing_alone(data, kept) or dict.fromkeys(kept, exc.reason)
            dropped.update(failing)
            kept = {block_id: text for block_id, text in kept.items() if block_id not in failing}
    return kept, dropped


def _failing_alone(data: bytes, edits: dict[str, str]) -> dict[str, str]:
    failing: dict[str, str] = {}
    for block_id, text in edits.items():
        try:
            edit_pdf_in_place(data, {block_id: text})
        except PdfInPlaceUnsupported as exc:
            failing[block_id] = exc.reason
    return failing
