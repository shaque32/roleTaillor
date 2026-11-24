"""Minimal style-sheet resolution: names, list/heading/bold inheritance, default font."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lxml import etree

from ._ooxml import A_NS, DocxPackage, w, wattr

_HEADING_NAME = re.compile(r"^heading\s*\d", re.IGNORECASE)
_OFF_VALUES = frozenset({"0", "false", "off", "none"})


def toggle_on(el: etree._Element | None) -> bool:
    """OOXML on/off property (w:b, w:i, ...): present and not explicitly off."""
    return el is not None and (wattr(el, "val") or "true").lower() not in _OFF_VALUES


@dataclass(frozen=True)
class StyleInfo:
    style_id: str
    name: str
    based_on: str | None
    has_numbering: bool
    has_outline_level: bool
    bold: bool | None


@dataclass
class StyleSheet:
    styles: dict[str, StyleInfo] = field(default_factory=dict)
    default_paragraph_style: str | None = None
    default_font: str | None = None
    default_size_pt: float | None = None
    theme_fonts: dict[str, str] = field(default_factory=dict)

    def name(self, style_id: str | None) -> str | None:
        info = self.styles.get(style_id or "")
        return info.name if info else style_id

    def _chain(self, style_id: str | None) -> list[StyleInfo]:
        chain: list[StyleInfo] = []
        current = style_id or self.default_paragraph_style
        while current and current in self.styles and len(chain) < 20:
            info = self.styles[current]
            if info in chain:
                break
            chain.append(info)
            current = info.based_on
        return chain

    def is_list(self, style_id: str | None) -> bool:
        return any(s.has_numbering or "list" in s.name.lower() for s in self._chain(style_id))

    def is_heading(self, style_id: str | None) -> bool:
        return any(
            _HEADING_NAME.match(s.name) or s.has_outline_level for s in self._chain(style_id)
        )

    def is_bold(self, style_id: str | None) -> bool:
        for info in self._chain(style_id):
            if info.bold is not None:
                return info.bold
        return False


def _theme_fonts(pkg: DocxPackage) -> dict[str, str]:
    for part in pkg.related(pkg.main_part, "/theme"):
        theme = pkg.xml(part)
        if theme is None:
            continue
        fonts = {}
        for kind in ("major", "minor"):
            latin = theme.find(f".//{{{A_NS}}}{kind}Font/{{{A_NS}}}latin")
            if latin is not None and latin.get("typeface"):
                fonts[kind] = latin.get("typeface", "")
        return fonts
    return {}


def run_font(rpr: etree._Element | None, theme: dict[str, str] | None = None) -> str | None:
    """Latin font named by an rPr's rFonts (resolving theme references when given)."""
    fonts = None if rpr is None else rpr.find(w("rFonts"))
    if fonts is None:
        return None
    explicit = wattr(fonts, "ascii") or wattr(fonts, "hAnsi")
    if explicit or not theme:
        return explicit
    ref = wattr(fonts, "asciiTheme") or wattr(fonts, "hAnsiTheme") or ""
    return theme.get("major" if ref.startswith("major") else "minor") if ref else None


def run_size_pt(rpr: etree._Element | None) -> float | None:
    sz = None if rpr is None else rpr.find(w("sz"))
    val = wattr(sz, "val")
    return int(val) / 2 if val and val.isdigit() else None


def _style_info(style: etree._Element) -> StyleInfo:
    ppr = style.find(w("pPr"))
    rpr = style.find(w("rPr"))
    bold_el = None if rpr is None else rpr.find(w("b"))
    based = style.find(w("basedOn"))
    style_id = wattr(style, "styleId") or ""
    return StyleInfo(
        style_id=style_id,
        name=wattr(style.find(w("name")), "val") or style_id,
        based_on=wattr(based, "val"),
        has_numbering=ppr is not None and ppr.find(w("numPr")) is not None,
        has_outline_level=ppr is not None and ppr.find(w("outlineLvl")) is not None,
        bold=None if bold_el is None else toggle_on(bold_el),
    )


def load_stylesheet(pkg: DocxPackage) -> StyleSheet:
    sheet = StyleSheet()
    root = next((pkg.xml(p) for p in pkg.related(pkg.main_part, "/styles")), None)
    if root is None:
        return sheet
    theme = sheet.theme_fonts = _theme_fonts(pkg)
    defaults = root.find(f"{w('docDefaults')}/{w('rPrDefault')}/{w('rPr')}")
    sheet.default_font = run_font(defaults, theme)
    sheet.default_size_pt = run_size_pt(defaults)
    for style in root.iter(w("style")):
        if wattr(style, "type") not in (None, "paragraph", "character"):
            continue
        info = _style_info(style)
        sheet.styles[info.style_id] = info
        if wattr(style, "type") == "paragraph" and wattr(style, "default") in ("1", "true", "on"):
            sheet.default_paragraph_style = info.style_id
            normal = style.find(w("rPr"))
            sheet.default_font = run_font(normal, theme) or sheet.default_font
            sheet.default_size_pt = run_size_pt(normal) or sheet.default_size_pt
    return sheet
