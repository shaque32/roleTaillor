"""Document contract shared by the documents engine and the AI pipeline.

The AI never sees or regenerates a whole document. It sees `Block`s (semantic text
nodes) and returns replacement text for some of them, keyed by `Block.id`. The
documents engine owns turning those edits back into a byte-faithful DOCX.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BlockKind = Literal["paragraph", "table_paragraph", "text_line"]


class Block(BaseModel):
    """One semantic text node, usually a DOCX paragraph.

    `id` is stable for a given source file: `p{n}` for body paragraph n (0-based,
    counting every w:p in document order, including empty ones), and
    `t{t}r{r}c{c}p{n}` for paragraph n inside table t, row r, cell c.
    PDF-sourced blocks use `l{n}`.
    """

    id: str
    kind: BlockKind = "paragraph"
    text: str
    style_name: str | None = None
    is_list_item: bool = False
    is_heading: bool = False
    # False when the paragraph holds content we must not touch in place
    # (hyperlinks, fields, drawings, tracked changes, content controls).
    editable: bool = True
    # Formatting tokens per run, e.g. [{"bold": true, "len": 12}, {"len": 40}].
    run_styles: list[dict] = Field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.text)


class ParsedDocument(BaseModel):
    source_format: Literal["docx", "pdf", "guided"]
    blocks: list[Block]
    # Page size, margins, default fonts, section count. Stored in
    # resume_versions.layout_metadata.
    layout_metadata: dict = Field(default_factory=dict)
    # Human-readable findings for resume_versions.extraction_findings, e.g.
    # {"code": "missing_section", "detail": "No education section found"}.
    findings: list[dict] = Field(default_factory=list)
    # True when the engine can attempt to rewrite blocks in place: DOCX, and PDFs with a text
    # layer (`edit_pdf_in_place`; it may still raise `PdfInPlaceUnsupported` for a given edit
    # and the caller then re-renders through a template). False for scanned PDFs.
    supports_in_place_edit: bool = True

    def block(self, block_id: str) -> Block:
        for b in self.blocks:
            if b.id == block_id:
                return b
        raise KeyError(block_id)

    def text_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.text.strip()]


class EditRejected(ValueError):
    """Raised when an edit targets a block that cannot be changed in place."""
