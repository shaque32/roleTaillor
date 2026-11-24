"""Errors raised by the documents engine (besides the contract's `EditRejected`)."""

from __future__ import annotations


class InvalidDocument(ValueError):
    """The uploaded bytes are not a readable DOCX/PDF package."""


class PdfConversionError(RuntimeError):
    """LibreOffice could not convert a DOCX to PDF (missing, crashed, or timed out)."""
