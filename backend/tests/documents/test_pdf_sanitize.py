from __future__ import annotations

from io import BytesIO

import pikepdf
import pytest

from roletailor.documents.errors import InvalidDocument
from roletailor.documents.pdf_layout import pdf_paragraphs
from roletailor.documents.pdf_sanitize import sanitize_pdf

from .pdf_helpers import helvetica_pdf


def _active_pdf() -> bytes:
    pdf = pikepdf.open(BytesIO(helvetica_pdf()))
    pdf.Root.OpenAction = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert(1)"))
    pdf.Root.AA = pikepdf.Dictionary(WC=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("x")))
    spec = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Filespec, F=pikepdf.String("evil.exe")))
    pdf.Root.Names = pikepdf.Dictionary(
        EmbeddedFiles=pikepdf.Dictionary(Names=pikepdf.Array([pikepdf.String("evil.exe"), spec])),
        JavaScript=pikepdf.Dictionary(Names=pikepdf.Array()))

    def link(action: pikepdf.Dictionary, **extra: object) -> pikepdf.Object:
        return pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=[0, 0, 50, 10], A=action, **extra))

    launch = link(pikepdf.Dictionary(S=pikepdf.Name.Launch, F=pikepdf.String("calc.exe")))
    js_link = link(pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("x")))
    bad_uri = link(pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String("file:///etc/passwd")))
    good = link(pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String("https://example.com/me")),
                AA=pikepdf.Dictionary(E=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("x"))))
    attach = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.FileAttachment,
                                                  Rect=[0, 0, 5, 5]))
    page = pdf.pages[0].obj
    page.Annots = pikepdf.Array([launch, js_link, bad_uri, good, attach])
    page.AA = pikepdf.Dictionary(O=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("x")))
    out = BytesIO()
    pdf.save(out)
    return out.getvalue()


def test_active_content_is_removed_and_safe_link_kept():
    data = _active_pdf()
    out = sanitize_pdf(data)
    pdf = pikepdf.open(BytesIO(out))
    assert "/OpenAction" not in pdf.Root and "/AA" not in pdf.Root
    names = pdf.Root.get("/Names")
    assert names is None or ("/EmbeddedFiles" not in names and "/JavaScript" not in names)
    page = pdf.pages[0].obj
    assert "/AA" not in page
    annots = list(page.Annots)
    assert len(annots) == 1
    assert str(annots[0].Subtype) == "/Link" and str(annots[0].A.URI) == "https://example.com/me"
    assert "/AA" not in annots[0]
    assert b"calc.exe" not in out and b"evil.exe" not in out and b"app.alert" not in out
    assert [p.text for p in pdf_paragraphs(out)] == [p.text for p in pdf_paragraphs(data)]


def test_output_is_deterministic():
    data = _active_pdf()
    assert sanitize_pdf(data) == sanitize_pdf(data)


def test_clean_pdf_is_returned_unchanged():
    data = helvetica_pdf()
    assert sanitize_pdf(data) is data


def test_mailto_link_and_xfa_form():
    pdf = pikepdf.open(BytesIO(helvetica_pdf()))
    mail = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=[0, 0, 5, 5],
        A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String("mailto:a@b.co"))))
    pdf.pages[0].obj.Annots = pikepdf.Array([mail])
    out = BytesIO()
    pdf.save(out)
    assert sanitize_pdf(out.getvalue()) == out.getvalue()
    pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array(), XFA=pikepdf.Array())
    out2 = BytesIO()
    pdf.save(out2)
    cleaned = pikepdf.open(BytesIO(sanitize_pdf(out2.getvalue())))
    assert "/AcroForm" not in cleaned.Root and len(cleaned.pages[0].Annots) == 1


def test_unreadable_input_raises():
    with pytest.raises(InvalidDocument):
        sanitize_pdf(b"not a pdf")


def test_strips_actions_and_files_outside_the_page_tree():
    pdf = pikepdf.open(BytesIO(helvetica_pdf()))
    launch = pikepdf.Dictionary(S=pikepdf.Name.Launch, F=pikepdf.String("calc.exe"))
    item = pdf.make_indirect(pikepdf.Dictionary(Title=pikepdf.String("Click me"), A=launch))
    pdf.Root.Outlines = pdf.make_indirect(pikepdf.Dictionary(First=item, Last=item, Count=1))
    field = pdf.make_indirect(pikepdf.Dictionary(
        FT=pikepdf.Name.Tx, T=pikepdf.String("f"),
        A=pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert(1)"))))
    pdf.Root.AcroForm = pikepdf.Dictionary(Fields=pikepdf.Array([field]))
    payload = pdf.make_stream(b"MZ-evil-executable-bytes", Type=pikepdf.Name.EmbeddedFile)
    spec = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Filespec, F=pikepdf.String("evil.exe"),
                                                EF=pikepdf.Dictionary(F=payload)))
    pdf.Root.AF = pikepdf.Array([spec])
    pdf.Root.Names = pikepdf.Dictionary(Dests=pikepdf.Dictionary(Names=pikepdf.Array()),
                                        Pages=pikepdf.Dictionary(Names=pikepdf.Array()))
    raw = BytesIO()
    pdf.save(raw, compress_streams=False)

    cleaned = sanitize_pdf(raw.getvalue())
    out = pikepdf.open(BytesIO(cleaned))
    for key in ("/Outlines", "/AcroForm", "/AF"):
        assert key not in out.Root
    assert list(out.Root.Names.keys()) == ["/Dests"]
    for marker in (b"calc.exe", b"app.alert", b"MZ-evil-executable-bytes", b"evil.exe"):
        assert marker not in cleaned
    assert len(out.pages) == 1
