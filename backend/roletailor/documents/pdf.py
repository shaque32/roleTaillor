"""PDF conversion (headless LibreOffice) and PDF text extraction."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from . import ocr
from ._analysis import looks_like_heading, missing_section_findings, strip_bullet
from ._ooxml import strip_external_relationships
from .errors import InvalidDocument, OcrError, OcrTimeout, PdfConversionError
from .model import Block, ParsedDocument
from .pdf_layout import continues, paragraph_is_heading, pdf_paragraphs

log = logging.getLogger(__name__)

POINTS_PER_INCH = 72


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
        # The DOCX is derived from an upload: drop anything LibreOffice would fetch.
        source.write_bytes(strip_external_relationships(data))
        command = [
            binary,
            f"-env:UserInstallation={(workdir / 'profile').as_uri()}",
            "--headless", "--norestore", "--nologo", "--nodefault", "--nolockcheck",
            "--convert-to", "pdf", "--outdir", str(workdir / "out"), str(source),
        ]
        # Own session, so a timeout kills soffice.bin too and not just the launcher. The
        # converter gets no credentials: only what it needs to start.
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TMPDIR")}
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={**env, "HOME": tmp}, start_new_session=True,
            )
        except OSError as exc:
            raise PdfConversionError(f"could not start LibreOffice: {exc}") from exc
        try:
            _, stderr_bytes = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise PdfConversionError(f"LibreOffice timed out after {timeout}s") from exc
        finally:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        result = subprocess.CompletedProcess(command, process.returncode, b"", stderr_bytes)
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


@dataclass(frozen=True)
class OcrOptions:
    """How a scanned PDF is read. `enabled=False` never touches Tesseract."""

    enabled: bool = True
    max_pages: int = 6
    deadline: float = 45.0


# layout_metadata["ocr_outcome"] on a scanned PDF that OCR was tried on but yielded no blocks.
# Absent when OCR was disabled, or when it succeeded.
OCR_NO_TEXT = "no_text"  # Tesseract ran on every page and found nothing
OCR_TIMEOUT = "timeout"  # a page or the whole read ran out of time
OCR_FAILED = "failed"  # too many pages, unreadable pages, Tesseract missing or crashed


def read_pdf_text(data: bytes, *, ocr: OcrOptions | bool = True) -> ParsedDocument:
    """Extract text lines from a PDF as `text_line` blocks (`l0`, `l1`, ...).

    Lines come from the geometric reader (`pdf_layout`), so block ids are the same ones the
    in-place writer (`pdf_writer`) uses. Visually wrapped lines are merged back into one block
    when the break looks like a wrap rather than a new item. Bullet glyphs are stripped and
    recorded as `is_list_item`. PDFs with text can be edited in place; scanned ones need OCR.
    `ocr=False` (or `OcrOptions(enabled=False)`) leaves scanned PDFs unread, with the
    `scanned_pdf_needs_ocr` finding, without starting Tesseract.
    """
    options = OcrOptions(enabled=ocr) if isinstance(ocr, bool) else ocr
    reader = _reader(data)
    paragraphs = pdf_paragraphs(data)
    blocks = [
        Block(
            id=p.id, kind="text_line", text=p.text, is_list_item=p.is_list_item,
            is_heading=paragraph_is_heading(p))
        for p in paragraphs
    ]

    if not blocks:
        return _read_scanned(data, reader, options)
    return ParsedDocument(
        source_format="pdf",
        blocks=blocks,
        layout_metadata=_pdf_layout(reader, len(blocks)),
        findings=missing_section_findings(blocks),
        supports_in_place_edit=True,
    )


def _read_scanned(data: bytes, reader: PdfReader, options: OcrOptions) -> ParsedDocument:
    """A PDF with no text layer: read it with OCR when Tesseract is available.

    OCR'd blocks have no reusable fonts or exact geometry, so they are never edited in
    place; the tailored resume is rendered through the ATS template. Without OCR (binary
    missing, too many pages, or a Tesseract failure) the upload keeps the
    `scanned_pdf_needs_ocr` finding and no blocks. When OCR was tried, the reason is in
    `layout_metadata["ocr_outcome"]` (see OCR_NO_TEXT, OCR_TIMEOUT, OCR_FAILED), so a caller
    in another process (the sandbox child has no log) can tell "found nothing" from "broke".
    """
    blocks: list[Block] = []
    findings: list[dict] = []
    outcome: str | None = None
    if options.enabled and reader.pages:
        if not ocr.ocr_available():
            outcome = OCR_FAILED
        else:
            try:
                pages = ocr.ocr_pdf_pages(data, max_pages=options.max_pages, deadline=options.deadline)
            except OcrTimeout as exc:
                log.warning("OCR timed out, leaving the PDF unread: %s", exc)
                outcome = OCR_TIMEOUT
            except (OcrError, InvalidDocument) as exc:
                log.warning("OCR failed, leaving the PDF unread: %s", exc)
                outcome = OCR_FAILED
            else:
                blocks = _ocr_blocks(pages)
                if blocks:
                    findings = [*ocr.ocr_findings(pages), *missing_section_findings(blocks)]
                else:
                    outcome = OCR_NO_TEXT
    if not blocks:
        findings = [{"code": "scanned_pdf_needs_ocr", "detail": (
            "No extractable text; the PDF looks scanned and needs OCR")}]
    layout = _pdf_layout(reader, len(blocks))
    if blocks:
        layout["ocr"] = True
        layout["ocr_mean_confidence"] = _mean_confidence(pages)
    elif outcome:
        layout["ocr_outcome"] = outcome
    return ParsedDocument(
        source_format="pdf", blocks=blocks, layout_metadata=layout, findings=findings,
        supports_in_place_edit=False,
    )


def _mean_confidence(pages: list[ocr.OcrPage]) -> float:
    weights = [(len(" ".join(p.lines).split()), p.mean_confidence) for p in pages]
    total = sum(w for w, _ in weights)
    return round(sum(w * c for w, c in weights) / total, 1) if total else 0.0


def merge_text_lines(lines: list[str]) -> list[tuple[str, bool]]:
    """Group one page's plain text lines into (text, is_list_item) paragraphs.

    The text-only counterpart of `pdf_layout.merge_lines` for OCR output, which has no
    reliable geometry: blank lines split paragraphs and wrapped lines are merged.
    """
    full_width = max((len(line) for line in lines), default=0)
    merged: list[tuple[str, bool]] = []
    previous = ""
    for line in lines:
        if not line:
            previous = ""
            continue
        if previous and merged and not looks_like_heading(merged[-1][0], all_bold=False) \
                and continues(previous, line, full_width):
            text, is_list = merged[-1]
            merged[-1] = (f"{text} {line}", is_list)
        else:
            merged.append(strip_bullet(line))
        previous = line
    return merged


def _ocr_blocks(pages: list[ocr.OcrPage]) -> list[Block]:
    paragraphs = [p for page in pages for p in merge_text_lines(page.lines)]
    return [
        Block(
            id=f"l{n}", kind="text_line", text=text, is_list_item=is_list,
            is_heading=not is_list and looks_like_heading(text, all_bold=False, allow_caps_only=n > 0),
        )
        for n, (text, is_list) in enumerate(paragraphs)
    ]


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
