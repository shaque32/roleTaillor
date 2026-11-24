"""Deterministic ATS-style scoring. Explainable and free: every point traces to a
keyword match, a section, or a formatting finding."""

from __future__ import annotations

from dataclasses import dataclass

from roletailor.domain.models import JobAnalysis, ResumeStructure, Scores
from roletailor.pipeline.text import contains_any, norm

WEIGHT = {"must": 3.0, "should": 2.0, "nice": 1.0}
FINDING_PENALTY = {
    "text_box_content": 15, "layout_table": 10, "images_present": 5, "many_fonts": 5,
    "header_footer_content": 3, "scanned_pdf_needs_ocr": 40,
}
CORE_SECTIONS = ("experience", "education", "skills")


@dataclass
class KeywordReport:
    matched: list[str]
    missing: list[str]
    coverage: float  # 0..100, importance weighted


def keyword_report(text: str, job: JobAnalysis) -> KeywordReport:
    matched, missing, got, total = [], [], 0.0, 0.0
    for k in job.keywords:
        w = WEIGHT[k.importance]
        total += w
        if contains_any(text, [k.term, *k.synonyms]):
            matched.append(k.term)
            got += w
        else:
            missing.append(k.term)
    return KeywordReport(matched, missing, 100.0 * got / total if total else 0.0)


def score(text: str, job: JobAnalysis, structure: ResumeStructure, findings: list[dict],
          *, page_count: int | None = None, page_limit: int = 2) -> Scores:
    kw = keyword_report(text, job)
    kinds = {s.kind for s in structure.sections}
    completeness = 100.0 * (sum(k in kinds for k in CORE_SECTIONS)
                            + bool(structure.contact.email) + bool(structure.contact.phone)) / 5
    formatting = 100.0 - sum(FINDING_PENALTY.get(f.get("code", ""), 0) for f in findings)
    if page_count and page_count > page_limit:
        formatting -= 20
    formatting = max(formatting, 0.0)

    t = norm(text)
    resp_terms = {w for r in job.responsibilities for w in norm(r).split() if len(w) > 5}
    resp_cov = 100.0 * sum(w in t for w in resp_terms) / len(resp_terms) if resp_terms else kw.coverage
    alignment = 0.7 * kw.coverage + 0.3 * resp_cov
    ats = 0.5 * kw.coverage + 0.2 * completeness + 0.3 * formatting
    return Scores(ats=_r(ats), job_alignment=_r(alignment), keyword_relevance=_r(kw.coverage),
                  formatting=_r(formatting))


def _r(x: float) -> float:
    return round(min(max(x, 0.0), 100.0), 2)
