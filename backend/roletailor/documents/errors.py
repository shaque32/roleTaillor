"""Errors raised by the documents engine (besides the contract's `EditRejected`)."""

from __future__ import annotations


class InvalidDocument(ValueError):
    """The uploaded bytes are not a readable DOCX/PDF package."""


class PdfConversionError(RuntimeError):
    """LibreOffice could not convert a DOCX to PDF (missing, crashed, or timed out)."""


class OcrError(RuntimeError):
    """OCR could not run (Tesseract missing, crashed, timed out) or the input is too large."""


class PdfInPlaceUnsupported(RuntimeError):
    """An edit cannot be applied to the PDF faithfully; the caller should re-render via a template."""

    def __init__(self, reason: str, block_id: str | None = None) -> None:
        super().__init__(f"{reason} (block {block_id})" if block_id else reason)
        self.reason = reason
        self.block_id = block_id
