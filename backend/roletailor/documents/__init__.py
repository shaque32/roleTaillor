"""Documents engine: parse resumes into blocks, apply block edits in place, render, convert."""

from .docx_reader import read_docx
from .docx_writer import apply_block_edits
from .errors import InvalidDocument, OcrError, PdfConversionError, PdfInPlaceUnsupported
from .model import Block, EditRejected, ParsedDocument
from .pdf import count_pdf_pages, docx_to_pdf, read_pdf_text
from .pdf_layout import pages_without_text
from .pdf_writer import PdfEditReport, edit_pdf_in_place, fit_pdf_edits
from .plain_text import read_plain_text
from .render import render_structured_docx

__all__ = [
    "Block",
    "EditRejected",
    "InvalidDocument",
    "OcrError",
    "ParsedDocument",
    "PdfConversionError",
    "PdfEditReport",
    "PdfInPlaceUnsupported",
    "apply_block_edits",
    "count_pdf_pages",
    "docx_to_pdf",
    "edit_pdf_in_place",
    "fit_pdf_edits",
    "pages_without_text",
    "read_docx",
    "read_pdf_text",
    "read_plain_text",
    "render_structured_docx",
]
