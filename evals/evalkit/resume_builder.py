"""Render a ResumeSpec to DOCX bytes. Two layouts: single column ("classic") and a
two-column layout table ("table"), which ATS parsers handle badly and our reader must."""

from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.shared import Inches, Pt

from evalkit.cases import ResumeSpec

DEFAULT_HEADINGS = {"summary": "Summary", "experience": "Experience", "skills": "Skills",
                    "education": "Education", "certifications": "Certifications"}


def fixture_resume(name: str) -> bytes:
    from tests.fixtures.make_fixtures import make_classic_resume, make_table_resume

    return {"classic": make_classic_resume, "table": make_table_resume}[name]()


def build_resume(spec: ResumeSpec) -> bytes:
    doc = Document()
    for section in doc.sections:
        section.page_width, section.page_height = Inches(8.5), Inches(11)
        section.left_margin = section.right_margin = Inches(0.75)
        section.top_margin = section.bottom_margin = Inches(0.6)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(10.5)
    normal.paragraph_format.space_after = Pt(2)
    titles = {**DEFAULT_HEADINGS, **spec.headings}

    name = doc.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = name.add_run(spec.name)
    run.bold, run.font.size = True, Pt(20)
    doc.add_paragraph(spec.contact).alignment = WD_ALIGN_PARAGRAPH.CENTER

    if spec.layout == "table":
        table = doc.add_table(rows=1, cols=2)
        left, right = table.rows[0].cells
        left.width, right.width = Inches(2.4), Inches(4.6)
        side, main = _Cell(left), _Cell(right)
    else:
        side = main = _Body(doc)

    if spec.summary:
        main.heading(titles["summary"])
        main.para(spec.summary)
    main.heading(titles["experience"])
    for r in spec.experience:
        p = main.para("")
        p.paragraph_format.tab_stops.add_tab_stop(
            Inches(7.0 if spec.layout == "classic" else 4.4), WD_TAB_ALIGNMENT.RIGHT)
        p.add_run(r.company).bold = True
        p.add_run(" — ")
        p.add_run(r.title).italic = True
        p.add_run(f"\t{r.dates}")
        for b in r.bullets:
            main.para(b, style="List Bullet")
    if spec.skills:
        side.heading(titles["skills"])
        for s in spec.skills:
            p = side.para("")
            p.add_run(s.label).bold = True
            p.add_run(" " + s.value.strip())
    if spec.education:
        side.heading(titles["education"])
        for e in spec.education:
            side.para(", ".join(x for x in (e.degree, e.school, e.year) if x))
    if spec.certifications:
        side.heading(titles["certifications"])
        for c in spec.certifications:
            side.para(c, style="List Bullet")

    out = BytesIO()
    doc.save(out)
    return out.getvalue()


class _Body:
    def __init__(self, doc):
        self.target = doc

    def para(self, text: str, style: str | None = None):
        return self.target.add_paragraph(text, style=style)

    def heading(self, title: str):
        p = self.para("")
        p.paragraph_format.space_before = Pt(8)
        run = p.add_run(title.upper())
        run.bold, run.font.size = True, Pt(11)
        return p


class _Cell(_Body):
    """Table cells start with one empty paragraph; reuse it for the first line."""

    def __init__(self, cell):
        super().__init__(cell)
        self._first = cell.paragraphs[0]

    def para(self, text: str, style: str | None = None):
        if self._first is not None:
            p, self._first = self._first, None
            p.text = text
            if style:
                p.style = style
            return p
        return self.target.add_paragraph(text, style=style)
