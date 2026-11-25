"""Font handling for in-place PDF editing: reuse a page's own fonts, or embed a metric-compatible one.

Two codecs share one tiny interface (`can_encode`, `encode`, `width`):

* `PdfFont` wraps a font dictionary already in the PDF. It can only draw glyphs it is known to
  have: those in its ToUnicode map, or any WinAnsi character for a non-embedded font. Subset
  fonts therefore usually cover just the characters the original text used.
* `SubstituteFont` wraps a system TrueType file (Carlito for Calibri, Liberation Sans for Arial,
  ...) that has the same advance widths as the original, so reflowing keeps the layout. It is
  subset and embedded as a Type0/CIDFontType2 Identity-H font by `embed_substitutes`.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Protocol

import pikepdf
from fontTools import subset
from fontTools.agl import toUnicode
from fontTools.ttLib import TTFont, TTLibError
from reportlab.pdfbase import pdfmetrics

FONT_MAP_ENV = "RT_PDF_FONT_MAP"
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_HEX_PAIR = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_HEX_RANGE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]+>|\[[^\]]*\])")
_HEX_TOKEN = re.compile(rb"<([0-9A-Fa-f]+)>")
_EMBEDDED_KEYS = ("/FontFile", "/FontFile2", "/FontFile3")


class FontCodec(Protocol):
    """What the writer needs from a font: availability, byte encoding and advance width."""

    def can_encode(self, text: str) -> bool: ...

    def encode(self, text: str) -> bytes: ...

    def width(self, text: str, size: float) -> float: ...


def strip_subset_prefix(name: str) -> str:
    return _SUBSET_PREFIX.sub("", name.lstrip("/"))


# --- fonts already in the PDF ------------------------------------------------------------------


@dataclass
class PdfFont:
    """A font dictionary of the PDF, with its code<->text maps and glyph widths (1/1000 em)."""

    base_name: str
    two_byte: bool
    code_to_text: dict[int, str]
    text_to_code: dict[str, int]
    widths: dict[int, float]
    default_width: float
    reusable: bool = True  # False for CMaps/encodings we do not understand (only used to measure advances)
    vertical: bool = False  # Identity-V: advances run down the page, so no horizontal advance is measurable
    _longest: int = field(default=1, repr=False)

    def __post_init__(self) -> None:
        self._longest = max((len(t) for t in self.text_to_code), default=1)

    def _split(self, text: str) -> list[str] | None:
        """Greedy longest-match split of `text` into encodable units, or None if impossible."""
        units: list[str] = []
        i = 0
        while i < len(text):
            for length in range(min(self._longest, len(text) - i), 0, -1):
                if text[i:i + length] in self.text_to_code:
                    units.append(text[i:i + length])
                    i += length
                    break
            else:
                return None
        return units

    def can_encode(self, text: str) -> bool:
        return self.reusable and self._split(text) is not None

    def encode(self, text: str) -> bytes:
        units = self._split(text)
        if units is None:
            raise ValueError(f"font {self.base_name} cannot encode {text!r}")
        size = 2 if self.two_byte else 1
        return b"".join(self.text_to_code[u].to_bytes(size, "big") for u in units)

    def width(self, text: str, size: float) -> float:
        units = self._split(text) or []
        return sum(self.code_width(self.text_to_code[u]) for u in units) * size / 1000

    def code_width(self, code: int) -> float:
        return self.widths.get(code, self.default_width)

    def decode(self, raw: bytes) -> list[tuple[int, float, bool]]:
        """Split a shown string into (code, width, is_word_space) triples."""
        if self.two_byte:
            codes = [int.from_bytes(raw[i:i + 2], "big") for i in range(0, len(raw) - 1, 2)]
            return [(c, self.code_width(c), False) for c in codes]
        return [(c, self.code_width(c), c == 32) for c in raw]


def parse_to_unicode(data: bytes) -> dict[int, str]:
    """Parse a ToUnicode CMap's bfchar and bfrange sections into {code: text}."""
    mapping: dict[int, str] = {}
    for section in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in _HEX_PAIR.findall(section):
            mapping[int(src, 16)] = _utf16(dst)
    for section in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in _HEX_RANGE.findall(section):
            first, last = int(lo, 16), int(hi, 16)
            if dst.startswith(b"["):
                for offset, token in enumerate(_HEX_TOKEN.findall(dst)):
                    mapping[first + offset] = _utf16(token)
                continue
            base = _utf16(dst[1:-1])
            for offset in range(min(last - first, 0xFFFF) + 1):
                mapping[first + offset] = base[:-1] + chr(ord(base[-1]) + offset) if base else ""
    return mapping


def _utf16(hex_digits: bytes) -> str:
    return bytes.fromhex(hex_digits.decode()).decode("utf-16-be", errors="replace")


def load_pdf_font(font: pikepdf.Dictionary) -> PdfFont | None:
    """Build a `PdfFont` from a font dictionary, or None for font kinds we cannot measure."""
    subtype = str(font.get("/Subtype", ""))
    try:
        if subtype == "/Type0":
            return _load_type0(font)
        if subtype in ("/TrueType", "/Type1", "/MMType1"):
            return _load_simple(font)
    except (pikepdf.PdfError, ValueError, KeyError, IndexError, TypeError):
        return None
    return None


def _to_unicode_map(font: pikepdf.Dictionary) -> dict[int, str]:
    stream = font.get("/ToUnicode")
    return parse_to_unicode(bytes(stream.read_bytes())) if stream is not None else {}


def _invert(code_to_text: dict[int, str]) -> dict[str, int]:
    inverse: dict[str, int] = {}
    for code in sorted(code_to_text):
        if code_to_text[code]:
            inverse.setdefault(code_to_text[code], code)
    return inverse


def _load_type0(font: pikepdf.Dictionary) -> PdfFont:
    descendant = font.DescendantFonts[0]
    encoding = font.get("/Encoding")
    vertical = isinstance(encoding, pikepdf.Name) and str(encoding) == "/Identity-V"
    identity = isinstance(encoding, pikepdf.Name) and str(encoding) == "/Identity-H"
    code_to_text = _to_unicode_map(font)
    return PdfFont(
        base_name=strip_subset_prefix(str(font.get("/BaseFont", ""))), two_byte=True,
        code_to_text=code_to_text, text_to_code=_invert(code_to_text),
        widths=_cid_widths(descendant.get("/W")), default_width=float(descendant.get("/DW", 1000)),
        reusable=identity and bool(code_to_text), vertical=vertical)


def _cid_widths(array: pikepdf.Array | None) -> dict[int, float]:
    """Parse a CIDFont /W array (`c [w1 w2 ...]` and `c_first c_last w` forms)."""
    widths: dict[int, float] = {}
    items = list(array) if array is not None else []
    i = 0
    while i < len(items):
        first = int(items[i])
        if i + 1 < len(items) and isinstance(items[i + 1], pikepdf.Array):
            for offset, w in enumerate(items[i + 1]):
                widths[first + offset] = float(w)
            i += 2
        else:
            last, w = int(items[i + 1]), float(items[i + 2])
            for cid in range(first, min(last, first + 0xFFFF) + 1):
                widths[cid] = w
            i += 3
    return widths


def _load_simple(font: pikepdf.Dictionary) -> PdfFont:
    base = strip_subset_prefix(str(font.get("/BaseFont", "")))
    descriptor = font.get("/FontDescriptor")
    embedded = descriptor is not None and any(key in descriptor for key in _EMBEDDED_KEYS)
    code_to_text = _to_unicode_map(font)
    reusable = True
    if not code_to_text and not embedded:
        declared = _declared_map(font.get("/Encoding"))
        if declared is None:
            reusable = False  # an encoding we cannot reproduce: measure with it, never draw with it
        else:
            code_to_text = declared
    return PdfFont(
        base_name=base, two_byte=False, code_to_text=code_to_text, text_to_code=_invert(code_to_text),
        widths=_simple_widths(font, base, code_to_text),
        default_width=float(descriptor.get("/MissingWidth", 0)) if descriptor is not None else 0.0,
        reusable=reusable)


_BASE_CODECS = {"/WinAnsiEncoding": "cp1252", "/MacRomanEncoding": "mac_roman"}


def _codec_map(codec: str) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for code in range(32, 256):
        try:
            mapping[code] = bytes([code]).decode(codec)
        except UnicodeDecodeError:
            continue
    return mapping


def _declared_map(encoding: object) -> dict[int, str] | None:
    """Code -> text for a non-embedded font from its /Encoding (WinAnsi when absent), or None if unknown."""
    base: object = encoding
    if isinstance(encoding, pikepdf.Dictionary):
        base = encoding.get("/BaseEncoding")
    if base is None:
        codec = "cp1252"
    elif isinstance(base, pikepdf.Name) and str(base) in _BASE_CODECS:
        codec = _BASE_CODECS[str(base)]
    else:
        return None
    mapping = _codec_map(codec)
    if isinstance(encoding, pikepdf.Dictionary) and "/Differences" in encoding:
        code = 0
        for item in encoding.Differences:
            if isinstance(item, pikepdf.Name):
                text = toUnicode(str(item)[1:])
                if text:
                    mapping[code] = text
                code += 1
            else:
                code = int(item)
    return mapping


def _simple_widths(font: pikepdf.Dictionary, base: str, code_to_text: dict[int, str]) -> dict[int, float]:
    if "/Widths" in font:
        first = int(font.get("/FirstChar", 0))
        return {first + i: float(w) for i, w in enumerate(font.Widths)}
    if base in pdfmetrics.standardFonts:
        widths = {}
        for code in range(32, 256):
            text = code_to_text.get(code) or _cp1252(code)
            if text:
                widths[code] = pdfmetrics.stringWidth(text, base, 1000)
        return widths
    return {}


def _cp1252(code: int) -> str:
    try:
        return bytes([code]).decode("cp1252")
    except UnicodeDecodeError:
        return ""


# --- substitute fonts --------------------------------------------------------------------------

# Longest names first so "dejavusansmono" is not read as "dejavusans".
_FAMILIES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("dejavusansmono",), "DejaVu Sans Mono"),
    (("dejavuserif",), "DejaVu Serif"),
    (("dejavusans",), "DejaVu Sans"),
    (("liberationmono", "cousine", "couriernew", "courier"), "Liberation Mono"),
    (("liberationserif", "timesnewroman", "tinos", "times"), "Liberation Serif"),
    (("liberationsans", "arimo", "arial", "helvetica"), "Liberation Sans"),
    (("calibri", "carlito"), "Carlito"),
    (("cambria", "caladea"), "Caladea"),
)


@dataclass(frozen=True)
class FontStyle:
    family: str
    bold: bool
    italic: bool

    @property
    def key(self) -> str:
        """Override-map key, e.g. `Carlito-BoldItalic` or `Liberation Sans-Regular`."""
        suffix = ("Bold" if self.bold else "") + ("Italic" if self.italic else "") or "Regular"
        return f"{self.family}-{suffix}"


def substitute_style(font_name: str) -> FontStyle | None:
    """Metric-compatible family and weight/slant for a PDF font name, if we know one."""
    name = strip_subset_prefix(font_name)
    flat = re.sub(r"[\s,_-]", "", name).lower()
    for aliases, family in _FAMILIES:
        if any(flat.startswith(alias) for alias in aliases):
            return FontStyle(
                family, bold=any(w in flat for w in ("bold", "black", "heavy")),
                italic=any(w in flat for w in ("italic", "oblique")))
    return None


def _font_overrides(overrides: Mapping[str, str | Path] | None) -> Mapping[str, str | Path]:
    if overrides is not None:
        return overrides
    raw = os.environ.get(FONT_MAP_ENV)
    return json.loads(raw) if raw else {}


@functools.lru_cache(maxsize=64)
def _fc_match(family: str, bold: bool, italic: bool) -> str | None:
    pattern = family + (":bold" if bold else "") + (":italic" if italic else "")
    try:
        out = subprocess.run(
            ["fc-match", "-f", "%{file}\n%{family}\n%{style}", pattern],
            capture_output=True, text=True, timeout=20, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    file, _, rest = out.partition("\n")
    families, _, styles = rest.partition("\n")
    if family.lower() not in families.lower():
        return None
    lowered = styles.lower()
    if bold and "bold" not in lowered or italic and not any(s in lowered for s in ("italic", "oblique")):
        return None
    return file or None


def resolve_font_file(style: FontStyle, overrides: Mapping[str, str | Path] | None = None) -> Path | None:
    """Font file for `style`: explicit override (arg or `RT_PDF_FONT_MAP`), else `fc-match`."""
    explicit = _font_overrides(overrides).get(style.key)
    if explicit:
        return Path(explicit)
    found = _fc_match(style.family, style.bold, style.italic)
    return Path(found) if found else None


class SubstituteFont:
    """A system TrueType font used for glyph availability and widths; one code is one glyph id."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._font = TTFont(path, fontNumber=0, lazy=True, recalcTimestamp=False)
        self._cmap: dict[int, str] = self._font.getBestCmap() or {}
        self._hmtx = self._font["hmtx"]
        self._upem = int(self._font["head"].unitsPerEm)
        self.used: set[str] = set()

    @classmethod
    def open(cls, path: Path) -> SubstituteFont | None:
        try:
            font = cls(path)
        except (OSError, TTLibError, KeyError):
            return None
        return font if "glyf" in font._font else None

    def _gid(self, char: str) -> int | None:
        name = self._cmap.get(ord(char))
        return self._font.getGlyphID(name) if name is not None else None

    def can_encode(self, text: str) -> bool:
        return all(self._gid(c) is not None for c in text)

    def encode(self, text: str) -> bytes:
        return b"".join(int(self._gid(c)).to_bytes(2, "big") for c in text)

    def width(self, text: str, size: float) -> float:
        total = sum(self._advance(c) for c in text)
        return total * size / self._upem

    def _advance(self, char: str) -> int:
        return self._hmtx[self._cmap[ord(char)]][0]

    def need(self, text: str) -> None:
        self.used.update(text)


def embed_substitute(pdf: pikepdf.Pdf, font: SubstituteFont) -> pikepdf.Object:
    """Subset `font` to the characters used and add it to `pdf` as a Type0/Identity-H font."""
    chars = sorted(font.used)
    options = subset.Options()
    options.retain_gids = True  # CIDToGIDMap Identity: PDF code == glyph id of the source font
    options.layout_features = []
    options.hinting = False
    options.notdef_outline = True
    options.name_IDs = [1, 2, 3, 4, 6]
    source = TTFont(font.path, fontNumber=0, recalcTimestamp=False)
    # fontTools warns about tables it cannot subset (e.g. FFTM); they are dropped harmlessly.
    logging.getLogger("fontTools.subset").setLevel(logging.ERROR)
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=[ord(c) for c in chars])
    subsetter.subset(source)
    out = BytesIO()
    source.save(out)
    data = out.getvalue()

    upem = int(source["head"].unitsPerEm)
    scale = 1000 / upem
    gids = {c: font._gid(c) for c in chars}
    widths = {gid: round(font._advance(c) * scale) for c, gid in gids.items() if gid is not None}
    ps_name = _ps_name(source) or font.path.stem
    tag = hashlib.sha1(f"{ps_name}{''.join(chars)}".encode()).hexdigest()[:6].upper()
    tag = "".join(chr(ord("A") + int(ch, 16) % 26) for ch in tag)
    base_font = pikepdf.Name("/" + f"{tag}+{ps_name}")

    file_stream = pdf.make_stream(data)
    file_stream.Length1 = len(data)
    head, hhea, post = source["head"], source["hhea"], source["post"]
    os2 = source.get("OS/2")
    descriptor = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.FontDescriptor, FontName=base_font, Flags=4,
        FontBBox=[round(v * scale) for v in (head.xMin, head.yMin, head.xMax, head.yMax)],
        ItalicAngle=float(post.italicAngle), Ascent=round(hhea.ascent * scale),
        Descent=round(hhea.descent * scale), StemV=80,
        CapHeight=round(getattr(os2, "sCapHeight", 0) * scale) or 700, FontFile2=file_stream))
    w_array = pikepdf.Array()
    for gid in sorted(widths):
        w_array.append(gid)
        w_array.append(pikepdf.Array([widths[gid]]))
    cid_font = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.CIDFontType2, BaseFont=base_font,
        CIDSystemInfo=pikepdf.Dictionary(Registry=pikepdf.String("Adobe"), Ordering=pikepdf.String("Identity"),
                                         Supplement=0),
        FontDescriptor=descriptor, CIDToGIDMap=pikepdf.Name.Identity, DW=0, W=w_array))
    return pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type0, BaseFont=base_font,
        Encoding=pikepdf.Name("/Identity-H"), DescendantFonts=[cid_font],
        ToUnicode=pdf.make_stream(_to_unicode_cmap(gids))))


def _ps_name(font: TTFont) -> str:
    record = font["name"].getName(6, 3, 1, 0x409) or font["name"].getName(6, 1, 0, 0)
    return re.sub(r"[^A-Za-z0-9-]", "", str(record)) if record else ""


def _to_unicode_cmap(gids: dict[str, int | None]) -> bytes:
    pairs = sorted((gid, char) for char, gid in gids.items() if gid is not None)
    parts = [
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap",
        "/CMapName /Adobe-Identity-UCS def /CMapType 2 def",
        "1 begincodespacerange <0000> <FFFF> endcodespacerange",
    ]
    for start in range(0, len(pairs), 100):
        chunk = pairs[start:start + 100]
        parts.append(f"{len(chunk)} beginbfchar")
        parts.extend(f"<{gid:04X}> <{char.encode('utf-16-be').hex().upper()}>" for gid, char in chunk)
        parts.append("endbfchar")
    parts.append("endcmap CMapName currentdict /CMap defineresource pop end end")
    return "\n".join(parts).encode()
