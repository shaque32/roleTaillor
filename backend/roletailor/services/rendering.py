"""Turn a stored resume version plus block edits into DOCX bytes.

DOCX and guided versions are edited in place on their stored DOCX (block ids address
its paragraphs). PDF-sourced versions have no faithful DOCX, so they are re-rendered
through the structured template from their (edited) blocks.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection

from roletailor.documents.model import Block, ParsedDocument
from roletailor.services import files

IN_PLACE_FORMATS = frozenset({"docx", "guided"})


@dataclass(frozen=True)
class Base:
    version: dict
    document: ParsedDocument
    docx: bytes | None  # None when the version cannot be edited in place

    @property
    def structure(self) -> dict | None:
        return (self.version["content"] or {}).get("structure")


def load_base(conn: Connection, version: dict) -> Base:
    content = version["content"] or {}
    source_format = content.get("source_format") or "docx"
    in_place = source_format in IN_PLACE_FORMATS and version["source_file_id"] is not None
    document = ParsedDocument(
        source_format=source_format,
        blocks=[Block.model_validate(b) for b in content.get("blocks", [])],
        layout_metadata=version["layout_metadata"] or {},
        findings=version["extraction_findings"] or [],
        supports_in_place_edit=in_place,
    )
    docx = files.read_bytes(conn, version["source_file_id"])[1] if in_place else None
    return Base(version=version, document=document, docx=docx)


def edited_blocks(document: ParsedDocument, edits: dict[str, str]) -> list[Block]:
    return [
        b.model_copy(update={"text": edits[b.id]}) if b.id in edits else b for b in document.blocks
    ]


def render_with_edits(base: Base, edits: dict[str, str], structure: dict | None) -> bytes:
    from roletailor import documents

    if base.docx is not None:
        return documents.apply_block_edits(base.docx, edits)
    sections = (structure or {}).get("sections") or None
    return documents.render_structured_docx(edited_blocks(base.document, edits), sections)
