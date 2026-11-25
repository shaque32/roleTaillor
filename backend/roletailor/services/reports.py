"""Small DOCX summaries for the ats_report and feedback_report exports."""

from __future__ import annotations

from io import BytesIO

from docx import Document

from roletailor.services.tailoring_runner import SIMULATION_LABEL

_SCORE_LABELS = {
    "ats": "ATS compatibility", "job_alignment": "Job alignment",
    "keyword_relevance": "Keyword relevance", "formatting": "Formatting",
}


def _save(doc) -> bytes:
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def ats_report(scores_after: dict, scores_before: dict | None, gaps: list[str], changes: list[dict]) -> bytes:
    doc = Document()
    doc.add_heading("ATS report", level=0)
    table = doc.add_table(rows=1, cols=3)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text, table.rows[0].cells[2].text = (
        "Score", "Before", "After")
    for key, label in _SCORE_LABELS.items():
        cells = table.add_row().cells
        before = (scores_before or {}).get(key)
        cells[0].text = label
        cells[1].text = "" if before is None else f"{float(before):.0f}"
        cells[2].text = "" if scores_after.get(key) is None else f"{float(scores_after[key]):.0f}"
    if gaps:
        doc.add_heading("Requirements without evidence in your resume", level=1)
        for gap in gaps:
            doc.add_paragraph(gap, style="List Bullet")
    keywords = sorted({k for c in changes for k in c.get("prioritized_keywords") or []})
    if keywords:
        doc.add_heading("Keywords emphasised", level=1)
        doc.add_paragraph(", ".join(keywords))
    return _save(doc)


def feedback_report(feedback: dict) -> bytes:
    doc = Document()
    doc.add_heading("Hiring manager simulation", level=0)
    doc.add_paragraph().add_run(SIMULATION_LABEL).italic = True
    if feedback.get("overall") is not None:
        doc.add_paragraph(f"Overall: {float(feedback['overall']):.0f} / 100")
    if feedback.get("interview_likelihood"):
        doc.add_paragraph(f"Simulated interview likelihood: {feedback['interview_likelihood']}")
    for key, title in (("strengths", "Strengths"), ("weaknesses", "Weaknesses"),
                       ("suggested_improvements", "Suggested improvements")):
        if feedback.get(key):
            doc.add_heading(title, level=1)
            for item in feedback[key]:
                doc.add_paragraph(item, style="List Bullet")
    if feedback.get("competitive_positioning"):
        doc.add_heading("Competitive positioning", level=1)
        doc.add_paragraph(feedback["competitive_positioning"])
    return _save(doc)
