"""Helpers for PDF tests: reportlab fixtures and a pixel-diff harness built on pypdfium2."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from roletailor.documents.pdf_layout import pdf_paragraphs

Box = tuple[int, float, float, float, float]  # page, x0, y0, x1, y1 in PDF points (y up)


def render_page(data: bytes, page: int = 0, dpi: int = 100) -> np.ndarray:
    """Render one page to an RGB array."""
    pdf = pdfium.PdfDocument(data)
    try:
        return np.asarray(pdf[page].render(scale=dpi / 72).to_pil().convert("RGB"))
    finally:
        pdf.close()


def block_boxes(data: bytes, block_ids: Iterable[str]) -> list[Box]:
    """Bounding boxes (points) of the lines of the given blocks, bullet glyph included."""
    wanted = set(block_ids)
    boxes: list[Box] = []
    for par in pdf_paragraphs(data):
        if par.id in wanted:
            for line in par.lines:
                left = line.bullet_x0 if line.bullet_x0 is not None else line.x0
                boxes.append((line.page, left, line.bottom, line.x1, line.top))
    return boxes


def pixel_diff(before: bytes, after: bytes, boxes: list[Box], *, page: int = 0, dpi: int = 100, pad: int = 4,
               ) -> tuple[float, int]:
    """Fraction of pixels that differ outside `boxes` (padded), and pixels that differ inside them."""
    a, b = render_page(before, page, dpi), render_page(after, page, dpi)
    assert a.shape == b.shape
    height, scale = a.shape[0], dpi / 72
    inside = np.zeros(a.shape[:2], dtype=bool)
    for box_page, x0, y0, x1, y1 in boxes:
        if box_page != page:
            continue
        left, right = int(x0 * scale) - pad, int(x1 * scale) + pad + 1
        top, bottom = int(height - y1 * scale) - pad, int(height - y0 * scale) + pad + 1
        inside[max(top, 0):bottom, max(left, 0):right] = True
    changed = (a != b).any(axis=2)
    return float(changed[~inside].sum() / changed.size), int(changed[inside].sum())


def font_file(family: str) -> Path | None:
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}|%{family}", family], capture_output=True, text=True,
                             check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    path, _, found = out.partition("|")
    return Path(path) if family.lower() in found.lower() else None


def helvetica_pdf() -> bytes:
    """Standard-14 Helvetica: heading, paragraph, hyphen bullets in the same string as their text, a date."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(72, 720, "SUMMARY")
    c.setFont("Helvetica", 10.5)
    c.drawString(72, 702, "Backend engineer building payment systems.")
    c.drawString(72, 684, "- Reduced latency by 40% across checkout services.")
    c.drawString(72, 666, "- Mentored four engineers on the platform team.")
    c.drawString(72, 648, "Acme Corp - Senior Engineer")
    c.drawRightString(540, 648, "2020 - 2023")
    c.save()
    return buf.getvalue()


def two_page_pdf() -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 10.5)
    c.drawString(72, 720, "First page keeps its text.")
    c.showPage()
    c.setFont("Helvetica", 10.5)
    c.drawString(72, 720, "Second page opening line.")
    c.drawString(72, 702, "Second page closing line.")
    c.save()
    return buf.getvalue()


def form_xobject_pdf() -> bytes:
    """One line drawn normally and one inside a Form XObject."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.beginForm("hidden")
    c.setFont("Helvetica", 10.5)
    c.drawString(72, 684, "Hidden inside a form.")
    c.endForm()
    c.setFont("Helvetica", 10.5)
    c.drawString(72, 702, "Visible on the page.")
    c.doForm("hidden")
    c.save()
    return buf.getvalue()


def ttf_embedded_pdf(path: Path) -> bytes:
    """A TrueType font embedded (and subset) by reportlab."""
    name = "TestEmbedded"
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(path)))
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont(name, 11)
    c.drawString(72, 702, "Platform engineer focused on reliability.")
    c.drawString(72, 684, "Built an internal developer portal.")
    c.save()
    return buf.getvalue()
