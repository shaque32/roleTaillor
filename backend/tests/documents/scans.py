"""Image-only (scanned) PDF fixtures, built from the classic resume."""

from __future__ import annotations

from functools import cache
from io import BytesIO

from PIL import Image

from tests.fixtures import make_classic_resume


@cache
def _resume_page() -> Image.Image:
    import pypdfium2 as pdfium

    from roletailor.documents import docx_to_pdf

    pdf = pdfium.PdfDocument(docx_to_pdf(make_classic_resume()))
    return pdf[0].render(scale=200 / 72, grayscale=True).to_pil().convert("RGB")


def _pdf(images: list[Image.Image]) -> bytes:
    out = BytesIO()
    images[0].save(out, format="PDF", resolution=200, save_all=True, append_images=images[1:])
    return out.getvalue()


@cache
def scanned_pdf(pages: int = 1) -> bytes:
    """`pages` copies of the rasterised resume page, with no text layer."""
    return _pdf([_resume_page()] * pages)


@cache
def blank_scanned_pdf(pages: int = 1) -> bytes:
    """White page(s): Tesseract runs and finds nothing."""
    white = Image.new("RGB", _resume_page().size, "white")
    return _pdf([white] * pages)
