"""Turn a stored resume version plus block edits into output bytes.

DOCX and guided versions are edited in place on their stored DOCX (block ids address
its paragraphs). Text-based PDF versions are edited in place on their stored PDF, keeping
the original layout and fonts. When a PDF edit cannot be done faithfully (a font without
the needed glyphs and no metric-compatible substitute, text that overflows its lines,
text inside form XObjects, scanned or OCR'd sources), the version is re-rendered through
the structured ATS template instead, and the reason is reported.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import Connection

from roletailor.documents.model import Block, ParsedDocument
from roletailor.services import files
from roletailor.storage import DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE

log = logging.getLogger(__name__)

IN_PLACE_FORMATS = frozenset({"docx", "guided"})
# content key recording that a PDF version's blocks address its stored PDF exactly.
PDF_IN_PLACE_KEY = "pdf_in_place"


@dataclass(frozen=True)
class Base:
    version: dict
    document: ParsedDocument
    docx: bytes | None  # None when the version cannot be edited in place as DOCX
    pdf: bytes | None = None  # set when the version can be edited in place as PDF

    @property
    def structure(self) -> dict | None:
        return (self.version["content"] or {}).get("structure")


@dataclass(frozen=True)
class Rendered:
    data: bytes
    media_type: str
    mode: str  # docx_in_place | pdf_in_place | template
    fallback_reason: str | None = None

    @property
    def extension(self) -> str:
        return ".pdf" if self.media_type == PDF_MEDIA_TYPE else ".docx"

    def summary(self) -> dict:
        return {"mode": self.mode, "fallback_reason": self.fallback_reason}


def load_base(conn: Connection, version: dict) -> Base:
    content = version["content"] or {}
    source_format = content.get("source_format") or "docx"
    file_id = version["source_file_id"]
    docx_in_place = source_format in IN_PLACE_FORMATS and file_id is not None
    pdf_in_place = source_format == "pdf" and file_id is not None and bool(content.get(PDF_IN_PLACE_KEY))
    docx = pdf = None
    if docx_in_place:
        docx = files.read_bytes(conn, file_id)[1]
    elif pdf_in_place:
        row, data = files.read_bytes(conn, file_id)
        pdf = data if row["media_type"] == PDF_MEDIA_TYPE else None
    document = ParsedDocument(
        source_format=source_format,
        blocks=[Block.model_validate(b) for b in content.get("blocks", [])],
        layout_metadata=version["layout_metadata"] or {},
        findings=version["extraction_findings"] or [],
        supports_in_place_edit=docx is not None or pdf is not None,
    )
    return Base(version=version, document=document, docx=docx, pdf=pdf)


def edited_blocks(document: ParsedDocument, edits: dict[str, str]) -> list[Block]:
    return [
        b.model_copy(update={"text": edits[b.id]}) if b.id in edits else b for b in document.blocks
    ]


def render_with_edits(base: Base, edits: dict[str, str], structure: dict | None) -> bytes:
    """DOCX bytes: the DOCX edited in place, or the ATS template for other sources."""
    from roletailor import documents

    if base.docx is not None:
        return documents.apply_block_edits(base.docx, edits)
    sections = (structure or {}).get("sections") or None
    return documents.render_structured_docx(edited_blocks(base.document, edits), sections)


def _pdf_in_place(base: Base, edits: dict[str, str]) -> tuple[bytes | None, str | None]:
    """In-place PDF bytes, or (None, reason) when the edit must fall back to the template."""
    from roletailor import documents

    if base.pdf is None:
        return None, None
    try:
        data, _report = documents.edit_pdf_in_place(base.pdf, edits)
    except documents.PdfInPlaceUnsupported as exc:
        log.info("PDF in-place edit fell back to template: %s", exc)
        return None, str(exc)[:300]
    return data, None


def render_primary(base: Base, edits: dict[str, str], structure: dict | None) -> Rendered:
    """The generation's main output, in the source's own format when that is possible."""
    if base.docx is not None:
        return Rendered(render_with_edits(base, edits, structure), DOCX_MEDIA_TYPE, "docx_in_place")
    pdf, reason = _pdf_in_place(base, edits)
    if pdf is not None:
        return Rendered(pdf, PDF_MEDIA_TYPE, "pdf_in_place")
    return Rendered(render_with_edits(base, edits, structure), DOCX_MEDIA_TYPE, "template", reason)


def render_pdf(base: Base, edits: dict[str, str], structure: dict | None) -> bytes:
    """PDF export: the original PDF edited in place when possible, else the DOCX converted."""
    from roletailor import documents

    pdf, _reason = _pdf_in_place(base, edits)
    if pdf is not None:
        return pdf
    return documents.docx_to_pdf(render_with_edits(base, edits, structure))


def pdf_addresses_blocks(pdf: bytes, blocks: list[Block]) -> bool:
    """Whether re-reading `pdf` yields exactly these block ids and texts, so a later
    iteration can edit the generated PDF in place with the same ids."""
    from roletailor import documents

    try:
        parsed = documents.read_pdf_text(pdf)
    except Exception:  # noqa: BLE001 - any read problem just means "use the template"
        return False
    if not parsed.supports_in_place_edit:
        return False
    return [(b.id, b.text) for b in parsed.blocks] == [(b.id, b.text) for b in blocks]
