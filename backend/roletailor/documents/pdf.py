"""PDF conversion (headless LibreOffice) and PDF text extraction."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ._analysis import (
    looks_like_heading,
    missing_section_findings,
    strip_bullet,
)
from .errors import InvalidDocument, PdfConversionError
from .model import Block, ParsedDocument

POINTS_PER_INCH = 72
# A line at least this fraction of the page's longest line is treated as wrapped prose.
_FULL_LINE_RATIO = 0.8
_CONTINUATION_ENDINGS = (",", ";", "-", "–", "/", "&", "(")
_SENTENCE_ENDINGS = (".", "!", "?", ":")


def soffice_path() -> str | None:
    """LibreOffice binary: `RT_SOFFICE` env var, else `soffice` on PATH."""
    return os.environ.get("RT_SOFFICE") or shutil.which("soffice")


def docx_to_pdf(data: bytes, timeout: int = 60) -> bytes:
    """Convert DOCX bytes to PDF with headless LibreOffice.

    Each call uses its own temp dir and LibreOffice user profile, so concurrent
    conversions (e.g. several Celery workers on one host) never share a lock file.
    """
    binary = soffice_path()
    if binary is None:
        raise PdfConversionError("LibreOffice (soffice) is not installed")
    with tempfile.TemporaryDirectory(prefix="rt-soffice-") as tmp:
        workdir = Path(tmp)
        source = workdir / "resume.docx"
        source.write_bytes(data)
        command = [
            binary,
            f"-env:UserInstallation={(workdir / 'profile').as_uri()}",
            "--headless", "--norestore", "--nologo", "--nodefault", "--nolockcheck",
            "--convert-to", "pdf", "--outdir", str(workdir / "out"), str(source),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=timeout, check=False,
                env={**os.environ, "HOME": tmp},
            )
        except subprocess.TimeoutExpired as exc:
            raise PdfConversionError(f"LibreOffice timed out after {timeout}s") from exc
        except OSError as exc:
            raise PdfConversionError(f"could not start LibreOffice: {exc}") from exc
        output = workdir / "out" / "resume.pdf"
        if result.returncode != 0 or not output.exists():
            stderr = result.stderr.decode(errors="replace").strip()[-500:]
            raise PdfConversionError(f"LibreOffice failed (exit {result.returncode}): {stderr}")
        return output.read_bytes()


def _reader(data: bytes) -> PdfReader:
    try:
        return PdfReader(BytesIO(data))
    except (PdfReadError, ValueError) as exc:
        raise InvalidDocument(f"not a readable PDF: {exc}") from exc


def count_pdf_pages(pdf: bytes) -> int:
    return len(_reader(pdf).pages)


def read_pdf_text(data: bytes) -> ParsedDocument:
    """Extract text lines from a PDF as `text_line` blocks (`l0`, `l1`, ...).

    Visually wrapped lines are merged back into one block when the break looks like a
    wrap rather than a new item (see `_continues`). Bullet glyphs are stripped and
    recorded as `is_list_item`. PDFs are never edited in place.
    """
    reader = _reader(data)
    paragraphs: list[tuple[str, bool]] = []
    for page in reader.pages:
        paragraphs.extend(_merge_lines(_page_lines(page.extract_text() or "")))

    blocks = []
    for n, (text, is_list) in enumerate(paragraphs):
        blocks.append(Block(
            id=f"l{n}",
            kind="text_line",
            text=text,
            is_list_item=is_list,
            is_heading=not is_list and looks_like_heading(
                text, all_bold=False, allow_caps_only=n > 0),
        ))

    findings: list[dict] = []
    if not blocks:
        findings.append({"code": "scanned_pdf_needs_ocr", "detail": (
            "No extractable text; the PDF looks scanned and needs OCR")})
    else:
        findings.extend(missing_section_findings(blocks))
    return ParsedDocument(
        source_format="pdf",
        blocks=blocks,
        layout_metadata=_pdf_layout(reader, len(blocks)),
        findings=findings,
        supports_in_place_edit=False,
    )


def _page_lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in text.splitlines()]


def _continues(previous: str, line: str, full_width: int) -> bool:
    """Whether `line` is a visual wrap of `previous` rather than a new paragraph."""
    if not line or strip_bullet(line)[1] or looks_like_heading(line, all_bold=False):
        return False
    if previous.endswith(_CONTINUATION_ENDINGS) or line[0].islower():
        return True
    return len(previous) >= _FULL_LINE_RATIO * full_width and not previous.endswith(
        _SENTENCE_ENDINGS)


def _merge_lines(lines: list[str]) -> list[tuple[str, bool]]:
    """Group a page's lines into (text, is_list_item) paragraphs; blank lines split."""
    full_width = max((len(line) for line in lines), default=0)
    merged: list[tuple[str, bool]] = []
    previous_raw = ""
    for line in lines:
        if not line:
            previous_raw = ""
            continue
        if previous_raw and merged and not looks_like_heading(merged[-1][0], all_bold=False) \
                and _continues(previous_raw, line, full_width):
            text, is_list = merged[-1]
            merged[-1] = (f"{text} {line}", is_list)
        else:
            text, is_list = strip_bullet(line)
            merged.append((text, is_list))
        previous_raw = line
    return merged


def _pdf_layout(reader: PdfReader, block_count: int) -> dict:
    meta: dict = {"page_count": len(reader.pages), "block_count": block_count}
    if reader.pages:
        box = reader.pages[0].mediabox
        width, height = float(box.width), float(box.height)
        meta.update(
            page_width_in=round(width / POINTS_PER_INCH, 3),
            page_height_in=round(height / POINTS_PER_INCH, 3),
            orientation="landscape" if width > height else "portrait",
        )
    return meta
