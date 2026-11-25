"""Content-stream interpreter for in-place PDF editing.

Walks a page's operators tracking just enough state (CTM, text matrices, text state) to know where
every text-showing operator starts and ends in user space. The writer uses that to delete exactly the
operators that draw an edited line, and to find the `ET` after which replacement text can be inserted
so that stream order (and therefore reading order for ATS parsers) is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pikepdf

from .pdf_fonts import PdfFont, load_pdf_font

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
_MAX_FORM_DEPTH = 4
_SHOW_OPERATORS = frozenset({"Tj", "TJ", "'", '"'})


def multiply(m1: Matrix, m2: Matrix) -> Matrix:
    """Matrix product for row vectors: apply `m1` first, then `m2`."""
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2,
    )


def invert(m: Matrix) -> Matrix | None:
    a, b, c, d, e, f = m
    det = a * d - b * c
    if abs(det) < 1e-12:
        return None
    ia, ib, ic, id_ = d / det, -b / det, -c / det, a / det
    return (ia, ib, ic, id_, -(e * ia + f * ic), -(e * ib + f * id_))


def translation(tx: float, ty: float) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


@dataclass(frozen=True)
class ShowEvent:
    """One text-showing operator with its user-space extent on the baseline."""

    index: int  # position in the instruction list (meaningless when `in_form`)
    operator: str
    start_x: float
    start_y: float
    end_x: float
    advance: float | None  # text-space advance; None when the font could not be measured
    unit: float  # font size * horizontal scale, converts `advance` to TJ thousandths
    in_form: bool
    operands: tuple
    rise: float = 0.0  # Ts in effect for this show
    render_mode: int = 0  # Tr in effect for this show


@dataclass(frozen=True)
class SplitState:
    """Text state right after a show operator: what is needed to close and re-open its text object."""

    ctm: Matrix
    tlm: Matrix  # text line matrix
    dx: float  # text-space distance the text matrix has moved from the line matrix along x
    dx_known: bool  # False if an unmeasurable show happened since the line matrix was set
    unit: float  # font size * horizontal scale
    balanced: bool  # no marked-content sequence opened inside this text object is still open
    clipping: bool  # a clipping render mode was used in this text object


@dataclass
class _TextState:
    font: PdfFont | None = None
    size: float = 0.0
    char_space: float = 0.0
    word_space: float = 0.0
    h_scale: float = 1.0
    leading: float = 0.0
    rise: float = 0.0
    render_mode: int = 0


@dataclass
class WalkResult:
    shows: list[ShowEvent] = field(default_factory=list)
    splits: dict[int, SplitState] = field(default_factory=dict)  # by show instruction index (page level)
    ctm_at_et: dict[int, Matrix] = field(default_factory=dict)


def walk(instructions: list, resources: pikepdf.Dictionary | None) -> WalkResult:
    """Interpret `instructions` (a page's parsed content stream) and report text positions."""
    result = WalkResult()
    _run(instructions, resources, IDENTITY, result, in_form=False, depth=0, font_cache={})
    return result


def _num(value: object) -> float:
    return float(value)  # type: ignore[arg-type]


def _run(
    instructions: list, resources: pikepdf.Dictionary | None, ctm: Matrix, result: WalkResult, *,
    in_form: bool, depth: int, font_cache: dict,
) -> None:
    stack: list[tuple[Matrix, _TextState]] = []
    state = _TextState()
    tm = tlm = IDENTITY
    dx, dx_known = 0.0, True  # tm's x offset from tlm
    mc_depth = bt_depth = 0
    clipping = False

    def set_line(matrix: Matrix) -> None:
        nonlocal tm, tlm, dx, dx_known
        tm = tlm = matrix
        dx, dx_known = 0.0, True

    def show(index: int, operator: str, operands: tuple, strings: list) -> None:
        nonlocal tm, dx, dx_known, clipping
        advance = _advance(strings, state)
        start = multiply(tm, ctm)
        end = multiply(translation(advance or 0.0, 0.0), multiply(tm, ctm))
        result.shows.append(ShowEvent(
            index=index, operator=operator, start_x=start[4], start_y=start[5], end_x=end[4],
            advance=advance, unit=state.size * state.h_scale, in_form=in_form, operands=operands,
            rise=state.rise, render_mode=state.render_mode))
        tm = multiply(translation(advance or 0.0, 0.0), tm)
        dx += advance or 0.0
        dx_known &= advance is not None
        clipping |= state.render_mode >= 4
        if not in_form:
            result.splits[index] = SplitState(
                ctm=ctm, tlm=tlm, dx=dx, dx_known=dx_known, unit=state.size * state.h_scale,
                balanced=mc_depth == bt_depth, clipping=clipping)

    for index, ins in enumerate(instructions):
        if not isinstance(ins, pikepdf.ContentStreamInstruction):
            continue
        op, args = str(ins.operator), list(ins.operands)
        try:
            if op == "q":
                stack.append((ctm, _TextState(**state.__dict__)))
            elif op == "Q" and stack:
                ctm, state = stack.pop()
            elif op == "cm":
                ctm = multiply(tuple(_num(a) for a in args), ctm)  # type: ignore[arg-type]
            elif op == "BT":
                set_line(IDENTITY)
                bt_depth, clipping = mc_depth, False
            elif op in ("BMC", "BDC"):
                mc_depth += 1
            elif op == "EMC":
                mc_depth -= 1
            elif op == "ET":
                if not in_form:
                    result.ctm_at_et[index] = ctm
            elif op == "Tf":
                state.font = _font(resources, str(args[0]), font_cache)
                state.size = _num(args[1])
            elif op == "Tc":
                state.char_space = _num(args[0])
            elif op == "Tw":
                state.word_space = _num(args[0])
            elif op == "Tz":
                state.h_scale = _num(args[0]) / 100
            elif op == "TL":
                state.leading = _num(args[0])
            elif op == "Ts":
                state.rise = _num(args[0])
            elif op == "Tr":
                state.render_mode = int(_num(args[0]))
            elif op in ("Td", "TD"):
                if op == "TD":
                    state.leading = -_num(args[1])
                set_line(multiply(translation(_num(args[0]), _num(args[1])), tlm))
            elif op == "Tm":
                set_line(tuple(_num(a) for a in args))  # type: ignore[arg-type]
            elif op == "T*":
                set_line(multiply(translation(0.0, -state.leading), tlm))
            elif op == "Tj":
                show(index, op, tuple(args), [bytes(args[0])])
            elif op == "TJ":
                show(index, op, tuple(args), [bytes(x) if isinstance(x, pikepdf.String) else float(x) for x in args[0]])
            elif op in ("'", '"'):
                if op == '"':
                    state.word_space, state.char_space = _num(args[0]), _num(args[1])
                set_line(multiply(translation(0.0, -state.leading), tlm))
                show(index, op, tuple(args), [bytes(args[-1])])
            elif op == "Do" and depth < _MAX_FORM_DEPTH:
                _enter_form(resources, str(args[0]), ctm, result, depth, font_cache)
        except (ValueError, TypeError, IndexError, KeyError, pikepdf.PdfError):
            continue  # a malformed operator must not stop us measuring the rest


def _font(resources: pikepdf.Dictionary | None, name: str, cache: dict) -> PdfFont | None:
    fonts = resources.get("/Font") if resources is not None else None
    if fonts is None or name not in fonts:
        return None
    obj = fonts[name]
    key = obj.objgen if obj.is_indirect else id(obj)
    if key not in cache:
        cache[key] = (obj, load_pdf_font(obj))  # keeping `obj` alive keeps its id() unique
    return cache[key][1]


def _advance(strings: list, state: _TextState) -> float | None:
    """Text-space distance the text matrix moves after showing `strings`, or None if unmeasurable."""
    if state.font is None or state.font.vertical:
        return None
    total = 0.0
    for item in strings:
        if isinstance(item, bytes):
            for _, width, is_space in state.font.decode(item):
                total += width / 1000 * state.size + state.char_space + (state.word_space if is_space else 0.0)
        else:
            total -= _num(item) / 1000 * state.size
    return total * state.h_scale


def _enter_form(resources: pikepdf.Dictionary | None, name: str, ctm: Matrix, result: WalkResult, depth: int,
                font_cache: dict) -> None:
    xobjects = resources.get("/XObject") if resources is not None else None
    if xobjects is None or name not in xobjects:
        return
    form = xobjects[name]
    if str(form.get("/Subtype")) != "/Form":
        return
    matrix = tuple(_num(v) for v in form.get("/Matrix", IDENTITY))
    inner = form.get("/Resources", resources)
    _run(
        pikepdf.parse_content_stream(form), inner, multiply(matrix, ctm),  # type: ignore[arg-type]
        result, in_form=True, depth=depth + 1, font_cache=font_cache)


def removal_replacement(event: ShowEvent) -> list[pikepdf.ContentStreamInstruction]:
    """Instructions that replace a deleted show operator, keeping its positioning side effects.

    `'` and `"` also move to the next line (and `"` sets word/char spacing), and any text drawn
    after the operator in the same `BT` starts where it ended. So the replacement keeps `T*` and
    the spacing operators and adds a number-only `TJ` that advances by the deleted text's width.
    """
    def instr(operator: str, *operands: object) -> pikepdf.ContentStreamInstruction:
        return pikepdf.ContentStreamInstruction(list(operands), pikepdf.Operator(operator))

    replacement: list[pikepdf.ContentStreamInstruction] = []
    if event.operator == '"':
        replacement += [instr("Tw", event.operands[0]), instr("Tc", event.operands[1])]
    if event.operator in ("'", '"'):
        replacement.append(instr("T*"))
    if event.advance and event.unit:
        replacement.append(instr("TJ", pikepdf.Array([-event.advance / event.unit * 1000])))
    return replacement
