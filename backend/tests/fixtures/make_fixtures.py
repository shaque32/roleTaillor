"""Generate realistic (fictional) data/ML-engineer resumes as DOCX bytes.

Run `python -m tests.fixtures.make_fixtures OUT_DIR` to write them to disk for a look.
"""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph

TEXT_WIDTH_IN = 7.0

CLASSIC_ROLES = [
    (
        "Northwind Analytics", "Senior Data Engineer", "Mar 2021 – Present",
        [
            "Designed a streaming feature pipeline on Kafka and Spark Structured Streaming "
            "serving 40M events/day to real-time fraud models.",
            "Cut nightly batch runtime from 6.5 to 1.8 hours by repartitioning Delta tables "
            "and moving transforms to dbt.",
            "Led migration of 120 Airflow DAGs to managed Airflow with zero missed SLAs.",
            "Mentored four engineers and introduced data contracts with Great Expectations.",
        ],
    ),
    (
        "Bluefin Health", "Machine Learning Engineer", "Jun 2018 – Feb 2021",
        [
            "Shipped a readmission-risk model (XGBoost) to production behind a FastAPI "
            "service, improving AUC from 0.71 to 0.79.",
            "Built an MLflow model registry and CI checks that reduced model rollout time "
            "from two weeks to two days.",
            "Partnered with clinicians to define labels and audit model fairness across "
            "patient cohorts.",
        ],
    ),
    (
        "Cascade Retail Group", "Data Analyst", "Jul 2016 – May 2018",
        [
            "Automated weekly demand reports in Python and SQL, saving 10 analyst hours per "
            "week.",
            "Built Tableau dashboards used by 30 store managers to plan inventory.",
        ],
    ),
]

SKILL_LINES = [
    ("Languages:", " Python, SQL, Scala, Go"),
    ("Data & ML:", " Spark, Kafka, Airflow, dbt, PyTorch, scikit-learn, XGBoost, MLflow"),
    ("Cloud:", " AWS (S3, EMR, SageMaker, Glue), Docker, Kubernetes, Terraform"),
]


def _to_bytes(doc: DocxDocument) -> bytes:
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def _base_document() -> DocxDocument:
    doc = Document()
    for section in doc.sections:
        section.page_width, section.page_height = Inches(8.5), Inches(11)
        section.left_margin = section.right_margin = Inches(0.75)
        section.top_margin = section.bottom_margin = Inches(0.6)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(2)
    return doc


def _section_heading(doc: DocxDocument, title: str) -> None:
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(8)
    run = para.add_run(title.upper())
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)


def _role_line(para: Paragraph, company: str, title: str, dates: str) -> None:
    para.paragraph_format.tab_stops.add_tab_stop(Inches(TEXT_WIDTH_IN), WD_TAB_ALIGNMENT.RIGHT)
    para.add_run(company).bold = True
    para.add_run(" — ")
    para.add_run(title).italic = True
    para.add_run(f"\t{dates}")


def make_classic_resume() -> bytes:
    """Single-column resume: name, contact, Summary, Experience, Skills, Education,
    Certifications. Role lines mix bold/italic runs with a right-aligned date tab; skill
    lines start with a bold label run; the degree line contains a line break."""
    doc = _base_document()

    name = doc.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name_run = name.add_run("Priya Raman")
    name_run.bold = True
    name_run.font.size = Pt(20)
    contact = doc.add_paragraph(
        "Seattle, WA | priya.raman@example.com | (206) 555-0147 | github.com/praman-example"
    )
    contact.alignment = WD_ALIGN_PARAGRAPH.CENTER

    _section_heading(doc, "Summary")
    doc.add_paragraph(
        "Data and machine learning engineer with 8 years of experience building reliable "
        "batch and streaming pipelines and taking models from notebook to production."
    )

    _section_heading(doc, "Experience")
    for company, title, dates, bullets in CLASSIC_ROLES:
        _role_line(doc.add_paragraph(), company, title, dates)
        for bullet in bullets:
            doc.add_paragraph(bullet, style="List Bullet")

    _section_heading(doc, "Skills")
    for label, value in SKILL_LINES:
        para = doc.add_paragraph()
        para.add_run(label).bold = True
        para.add_run(value)

    _section_heading(doc, "Education")
    school = doc.add_paragraph()
    school.paragraph_format.tab_stops.add_tab_stop(Inches(TEXT_WIDTH_IN), WD_TAB_ALIGNMENT.RIGHT)
    school.add_run("University of Washington").bold = True
    school.add_run("\t2016")
    degree = doc.add_paragraph()
    degree_run = degree.add_run("B.S. Computer Science")
    degree_run.italic = True
    degree_run.add_break()
    degree.add_run("Minor in Statistics")

    _section_heading(doc, "Certifications")
    for cert in ("AWS Certified Machine Learning – Specialty (2023)",
                 "Databricks Certified Data Engineer Professional (2022)"):
        doc.add_paragraph(cert, style="List Bullet")
    return _to_bytes(doc)


def _add_hyperlink(para: Paragraph, url: str, text: str) -> None:
    rel_id = para.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), rel_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    rpr.extend([color, underline])
    t = OxmlElement("w:t")
    t.text = text
    run.extend([rpr, t])
    link.append(run)
    para._p.append(link)


def make_table_resume() -> bytes:
    """Two-column layout table (skills/education left, experience right) with a nested
    proficiency table in the left cell and a mailto hyperlink in the contact line."""
    doc = _base_document()
    doc.add_paragraph("Marcus Okafor", style="Title")
    contact = doc.add_paragraph("Austin, TX | ")
    _add_hyperlink(contact, "mailto:marcus.okafor@example.com", "marcus.okafor@example.com")
    contact.add_run(" | (512) 555-0193")

    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    left, right = table.rows[0].cells
    left.width, right.width = Inches(2.4), Inches(4.6)

    left.paragraphs[0].text = "Skills"
    left.paragraphs[0].style = doc.styles["Heading 2"]
    left.add_paragraph("Python, SQL, Spark, Airflow, Snowflake, Terraform")
    proficiency = left.add_table(rows=2, cols=2)
    for row, (skill, level) in zip(proficiency.rows, [("Python", "Expert"), ("SQL", "Expert")],
                                   strict=True):
        row.cells[0].text, row.cells[1].text = skill, level
    left.add_paragraph("Education", style="Heading 2")
    left.add_paragraph("M.S. Data Science, University of Texas at Austin, 2019")

    right.paragraphs[0].text = "Experience"
    right.paragraphs[0].style = doc.styles["Heading 2"]
    role = right.add_paragraph()
    role.add_run("Lattice Energy").bold = True
    role.add_run(" — Data Engineer, 2019 – Present")
    for bullet in (
        "Built Snowflake ELT pipelines processing 2 TB/day of smart-meter readings.",
        "Deployed a load-forecasting model that reduced peak-demand error by 18%.",
    ):
        right.add_paragraph(bullet, style="List Bullet")
    return _to_bytes(doc)


def main(out_dir: str) -> None:
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "classic_resume.docx").write_bytes(make_classic_resume())
    (target / "table_resume.docx").write_bytes(make_table_resume())


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
