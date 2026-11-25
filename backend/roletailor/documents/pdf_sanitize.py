"""Strip active content from a PDF before it is shared.

Layout-preserving exports are built from the user's uploaded PDF and are later shared through
links, so scripts, launch actions, embedded files and form submissions must not ride along. Only
what could execute or exfiltrate is removed; pages, fonts and visible content are untouched.
"""

from __future__ import annotations

from io import BytesIO

import pikepdf

from .errors import InvalidDocument

_SAFE_URI_PREFIXES = ("http://", "https://", "mailto:")


def sanitize_pdf(data: bytes) -> bytes:
    """`data` without active content, or `data` itself (same bytes) when nothing had to go."""
    try:
        pdf = pikepdf.open(BytesIO(data))
    except pikepdf.PdfError as exc:
        raise InvalidDocument(f"not a readable PDF: {exc}") from exc
    with pdf:
        try:
            changed = _strip_catalog(pdf)
            for page in pdf.pages:
                changed |= _strip_page(page)
        except pikepdf.PdfError as exc:
            raise InvalidDocument(f"not a readable PDF: {exc}") from exc
        if not changed:
            return data
        out = BytesIO()
        pdf.save(out, deterministic_id=True)
    return out.getvalue()


def _drop(node: pikepdf.Dictionary, key: str) -> bool:
    if key in node:
        del node[key]
        return True
    return False


# Catalog entries that can run, submit, attach or launch something. A resume needs none
# of them, so they are removed outright instead of being inspected for bad actions:
# bookmarks (/Outlines) and form fields (/AcroForm) can carry Launch and JavaScript
# actions, /AF and /Collection carry embedded files.
_CATALOG_DROP = ("/OpenAction", "/AA", "/AcroForm", "/AF", "/Collection", "/Perms", "/Outlines",
                 "/URI", "/Threads", "/Requirements")
# The only name tree kept: named destinations, which internal links jump to.
_NAMES_KEEP = "/Dests"


def _strip_catalog(pdf: pikepdf.Pdf) -> bool:
    root = pdf.Root
    changed = False
    for key in _CATALOG_DROP:
        changed |= _drop(root, key)
    names = root.get("/Names")
    if names is not None:
        if isinstance(names, pikepdf.Dictionary):
            for key in [k for k in list(names) if k != _NAMES_KEEP]:
                changed |= _drop(names, key)
        else:
            changed |= _drop(root, "/Names")
    return changed


def _strip_page(page: pikepdf.Page) -> bool:
    changed = _drop(page.obj, "/AA")
    annots = page.obj.get("/Annots")
    if not isinstance(annots, pikepdf.Array):
        return changed
    kept = []
    for annot in annots:
        if not isinstance(annot, pikepdf.Dictionary) or not _is_safe_link(annot):
            changed = True
            continue
        changed |= _drop(annot, "/AA")
        kept.append(annot)
    if len(kept) != len(annots):
        page.obj.Annots = pikepdf.Array(kept)
    return changed


def _is_safe_link(annot: pikepdf.Dictionary) -> bool:
    if str(annot.get("/Subtype", "")) != "/Link":
        return False
    action = annot.get("/A")
    if action is None:
        return True  # a plain destination link navigates inside the document
    if not isinstance(action, pikepdf.Dictionary) or str(action.get("/S", "")) != "/URI":
        return False
    uri = action.get("/URI")
    if not isinstance(uri, pikepdf.String):
        return False
    return bytes(uri).decode("latin-1").strip().lower().startswith(_SAFE_URI_PREFIXES)
