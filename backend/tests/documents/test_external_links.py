from __future__ import annotations

import io
import zipfile

import pytest

from roletailor.documents._ooxml import strip_external_relationships
from tests.fixtures import make_classic_resume

RELS = "word/_rels/document.xml.rels"
NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


@pytest.fixture(scope="module")
def sample_docx() -> bytes:
    return make_classic_resume()


def _with_rels(docx: bytes, extra: str) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(docx))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == RELS:
                data = data.replace(b"</Relationships>", extra.encode() + b"</Relationships>")
            target.writestr(info.filename, data)
    return out.getvalue()


def test_external_fetches_are_removed_and_hyperlinks_kept(sample_docx: bytes):
    hostile = _with_rels(sample_docx, (
        f'<Relationship Id="rIdX1" Type="{OFFICE}/image" Target="file:///etc/hostname" TargetMode="External"/>'
        f'<Relationship Id="rIdX2" Type="{OFFICE}/oleObject" Target="http://169.254.169.254/" TargetMode="External"/>'
        f'<Relationship Id="rIdX3" Type="{OFFICE}/attachedTemplate" Target="http://10.0.0.1/t.dotm"'
        ' TargetMode="External"/>'
        f'<Relationship Id="rIdX4" Type="{OFFICE}/hyperlink" Target="https://example.com/me" TargetMode="External"/>'
    ))
    cleaned = strip_external_relationships(hostile)
    rels = zipfile.ZipFile(io.BytesIO(cleaned)).read(RELS).decode()
    assert "file:///etc/hostname" not in rels and "169.254.169.254" not in rels and "10.0.0.1" not in rels
    assert "https://example.com/me" in rels
    assert zipfile.ZipFile(io.BytesIO(cleaned)).testzip() is None


def test_clean_documents_are_returned_unchanged(sample_docx: bytes):
    assert strip_external_relationships(sample_docx) is sample_docx
