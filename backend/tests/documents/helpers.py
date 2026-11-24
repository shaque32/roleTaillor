"""Shared helpers for documents-engine tests."""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from io import BytesIO

from docx import Document
from docx.oxml import parse_xml
from lxml import etree

from roletailor.documents._ooxml import W_NS, body_of, iter_paragraphs

W_DECL = f'xmlns:w="{W_NS}"'


def zip_parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(BytesIO(data)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def paragraph_xml(data: bytes) -> dict[str, bytes]:
    """Serialized XML of every block's paragraph, keyed by block id."""
    root = etree.fromstring(zip_parts(data)["word/document.xml"])
    return {ref.block_id: etree.tostring(ref.element) for ref in iter_paragraphs(body_of(root))}


def modify_docx(data: bytes, mutate: Callable[[object], None]) -> bytes:
    """Load with python-docx, let `mutate(document)` change it, and save."""
    doc = Document(BytesIO(data))
    mutate(doc)
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def append_paragraph_xml(data: bytes, inner_xml: str) -> bytes:
    """Append a body paragraph built from raw `<w:p>` XML (w: prefix declared for you)."""
    xml = inner_xml.replace("<w:p>", f"<w:p {W_DECL}>", 1)

    def mutate(doc) -> None:
        body = doc.element.body
        body.insert(len(body) - 1, parse_xml(xml))  # before the final sectPr

    return modify_docx(data, mutate)
