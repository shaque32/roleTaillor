"""Documents engine: parse resumes into blocks, apply block edits in place, render, convert."""

from .docx_reader import read_docx
from .docx_writer import apply_block_edits
from .errors import InvalidDocument, PdfConversionError
from .model import Block, EditRejected, ParsedDocument
from .pdf import count_pdf_pages, docx_to_pdf, read_pdf_text
from .plain_text import read_plain_text
from .render import render_structured_docx

__all__ = [
    "Block",
    "EditRejected",
    "InvalidDocument",
    "ParsedDocument",
    "PdfConversionError",
    "apply_block_edits",
    "count_pdf_pages",
    "docx_to_pdf",
    "read_docx",
    "read_pdf_text",
    "read_plain_text",
    "render_structured_docx",
]
