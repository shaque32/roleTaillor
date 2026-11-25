"""OCR for scanned PDFs: pypdfium2 rasterises, the Tesseract CLI reads.

Both tools are permissively licensed (Apache/BSD); there is deliberately no PyMuPDF,
Ghostscript or pytesseract. Tesseract is called as a subprocess and its TSV output is
parsed here, so the only runtime requirement is the `tesseract` binary.
"""

from __future__ import annotations

import csv
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from .errors import InvalidDocument, OcrError

DEFAULT_DPI = 300
# Neither rendered side may exceed this; bounds memory for oversized page boxes.
MAX_PIXELS_PER_SIDE = 4000
LOW_CONFIDENCE = 70.0
_POINTS_PER_INCH = 72
# Glyphs OCR commonly returns for a bullet dot and that are never real line-initial text.
_UNAMBIGUOUS_BULLET_RE = re.compile(r"^[°«»■▪●¢©]\s*(?=\S)")
# "+" and "*" also start real text ("+44 20 7946 0958", "*nix"), so they need a following space.
_SPACED_BULLET_RE = re.compile(r"^[+*]\s+(?=\S)")
# Letters OCR confuses with a bullet dot ("e Built ...", "o Led ...").
# Only when a capital or digit follows: no real sentence starts with a lone "e"/"o" and then
# a capitalised word. Tesseract sometimes adds stray marks ("§", "=") right after the dot.
_AMBIGUOUS_BULLET_RE = re.compile(r"^[eo]\s+(?:[§=]+\s*)?(?=[A-Z0-9])")
_BULLET_NOISE_RE = re.compile(r"^• [§=]+\s*")
_MIN_AMBIGUOUS_LINES = 2


@dataclass
class OcrPage:
    index: int
    lines: list[str]
    mean_confidence: float  # 0-100, word-weighted


def tesseract_path() -> str | None:
    """Tesseract binary: `RT_TESSERACT` env var, else `tesseract` on PATH."""
    return os.environ.get("RT_TESSERACT") or shutil.which("tesseract")


def ocr_available() -> bool:
    return tesseract_path() is not None


def ocr_pdf_pages(
    data: bytes,
    page_indexes: list[int] | None = None,
    *,
    dpi: int = DEFAULT_DPI,
    lang: str = "eng",
    timeout: int = 20,
    max_pages: int = 6,
    deadline: float = 45.0,
) -> list[OcrPage]:
    """OCR the given pages (default: all) of a PDF.

    Raises `OcrError` when the binary is missing, the document has more than `max_pages`
    pages to read, a page cannot be rendered, Tesseract fails or exceeds `timeout` seconds
    on a page, or the whole read exceeds `deadline` seconds (so one upload cannot monopolise
    a worker); `InvalidDocument` when the bytes are not a readable PDF.
    """
    binary = tesseract_path()
    if binary is None or shutil.which(binary) is None:
        raise OcrError(f"Tesseract is not installed or not executable: {binary}")
    pdf = _open_pdf(data)
    try:
        indexes = list(range(len(pdf))) if page_indexes is None else list(page_indexes)
        if len(indexes) > max_pages:
            raise OcrError(f"refusing to OCR {len(indexes)} pages (limit {max_pages})")
        if any(not 0 <= i < len(pdf) for i in indexes):
            raise OcrError(f"page index out of range for a {len(pdf)}-page PDF")
        pages = []
        started = time.monotonic()
        for index in indexes:
            remaining = deadline - (time.monotonic() - started)
            if remaining <= 0:
                raise OcrError(f"OCR exceeded its {deadline:.0f}s budget")
            image = _render_page(pdf, index, dpi)
            page_timeout = max(1, min(timeout, math.ceil(remaining)))
            lines, confidence = parse_tsv(_run_tesseract(binary, image, lang, page_timeout))
            pages.append(OcrPage(index=index, lines=lines, mean_confidence=confidence))
        return pages
    finally:
        pdf.close()


def _open_pdf(data: bytes):
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise InvalidDocument(f"not a readable PDF: {exc}") from exc


def _render_page(pdf, index: int, dpi: int):
    """Grayscale PIL image of one page, scaled down if it would exceed the pixel cap."""
    import pypdfium2 as pdfium

    try:
        page = pdf[index]
    except pdfium.PdfiumError as exc:
        raise OcrError(f"could not load page {index + 1}: {exc}") from exc
    try:
        width, height = page.get_size()
        scale = dpi / _POINTS_PER_INCH
        scale = min(scale, MAX_PIXELS_PER_SIDE / max(width, height, 1.0))
        return page.render(scale=scale, grayscale=True).to_pil().convert("L")
    except pdfium.PdfiumError as exc:
        raise OcrError(f"could not render page {index + 1}: {exc}") from exc
    finally:
        page.close()


def _run_tesseract(binary: str, image, lang: str, timeout: int) -> str:
    """Run Tesseract on one image in a private temp dir; returns its TSV output."""
    with tempfile.TemporaryDirectory(prefix="rt-ocr-") as tmp:
        source = Path(tmp) / "page.png"
        image.save(source)
        command = [binary, str(source), "stdout", "--psm", "3", "-l", lang, "tsv"]
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=timeout, check=False,
                # One thread per process: concurrent workers must not oversubscribe CPUs.
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrError(f"Tesseract timed out after {timeout}s") from exc
        except OSError as exc:
            raise OcrError(f"could not start Tesseract: {exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()[-500:]
        raise OcrError(f"Tesseract failed (exit {result.returncode}): {stderr}")
    return result.stdout.decode("utf-8", errors="replace")


def parse_tsv(tsv: str) -> tuple[list[str], float]:
    """Turn Tesseract TSV into (lines, mean word confidence).

    Words are grouped by (block, paragraph, line) in file order, which is Tesseract's reading
    order. A "" separator is emitted between paragraphs/blocks because the PDF line merger
    treats blank lines as paragraph breaks. Rows with conf -1 (structural rows) and empty
    words are ignored, including in the confidence average.
    """
    groups: dict[tuple[str, str], dict[str, list[str]]] = {}
    confidences: list[float] = []
    reader = csv.DictReader(StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
    for row in reader:
        word = (row.get("text") or "").strip()
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            continue
        if conf < 0 or not word:
            continue
        confidences.append(conf)
        para = groups.setdefault((row["block_num"], row["par_num"]), {})
        para.setdefault(row["line_num"], []).append(word)

    lines: list[str] = []
    for paragraph in groups.values():
        paragraph_lines = [" ".join(" ".join(words).split()) for words in paragraph.values()]
        paragraph_lines = [line for line in paragraph_lines if line]
        if paragraph_lines:
            if lines:
                lines.append("")
            lines.extend(paragraph_lines)
    mean = sum(confidences) / len(confidences) if confidences else 0.0
    return _normalise_bullets(lines), round(mean, 1)


def _normalise_bullets(lines: list[str]) -> list[str]:
    """Rewrite OCR bullet artefacts at line start to "• " across one page's lines.

    Unambiguous non-word glyphs (° « » ■ ▪ ● ¢ ©) are always mapped; "+" and "*" only when a
    space follows, so "+44 ..." phone numbers and "*nix" survive. The letters "e" and
    "o" (how Tesseract often reads a round bullet) are only mapped when followed by a capital
    or digit and at least two lines on the page start that way, so a lone "o Led a team" is
    left alone. Tesseract usually puts each bullet in its own paragraph, so the count is per
    page rather than per paragraph.
    """
    result = [_SPACED_BULLET_RE.sub("• ", _UNAMBIGUOUS_BULLET_RE.sub("• ", line)) for line in lines]
    if sum(bool(_AMBIGUOUS_BULLET_RE.match(line)) for line in result) >= _MIN_AMBIGUOUS_LINES:
        result = [_AMBIGUOUS_BULLET_RE.sub("• ", line) for line in result]
    return [_BULLET_NOISE_RE.sub("• ", line) for line in result]


def ocr_findings(pages: list[OcrPage]) -> list[dict]:
    """Findings describing an OCR read; low confidence adds a second, heavier finding."""
    words_weight = [(len(" ".join(p.lines).split()), p.mean_confidence) for p in pages]
    total = sum(w for w, _ in words_weight)
    mean = sum(w * c for w, c in words_weight) / total if total else 0.0
    findings = [{"code": "ocr_applied", "detail": (
        f"Text was read with OCR from {len(pages)} scanned page(s); mean confidence {mean:.0f}%")}]
    if mean < LOW_CONFIDENCE:
        findings.append({"code": "ocr_low_confidence", "detail": (
            f"OCR confidence is low ({mean:.0f}%); review the extracted text for errors")})
    return findings
