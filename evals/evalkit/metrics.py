"""Per-case scoring that does not trust the pipeline's own validators.

Everything here is deterministic and recomputed from the source resume, the job text,
and the final edits, so a bug in a pipeline gate cannot hide a fabrication from the eval.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from evalkit.cases import EvalCase
from roletailor.domain.models import TailoringResult
from roletailor.pipeline import scoring
from roletailor.pipeline.text import bare_numbers, clean, contains_term, tech_terms

# A block that grows or shrinks more than this is a layout risk even if it passed.
LENGTH_WARN_RATIO = 0.25


@dataclass
class CaseMetrics:
    fabrications: list[dict] = field(default_factory=list)
    changes: int = 0
    reverted: int = 0
    coverage_before: float = 0.0
    coverage_after: float = 0.0
    ats_before: float = 0.0
    ats_after: float = 0.0
    max_length_drift: float = 0.0  # largest |new-old|/old across edited blocks
    length_outliers: list[str] = field(default_factory=list)
    total_chars_delta: int = 0
    gaps_reported: list[str] = field(default_factory=list)
    expected_gaps_missed: list[str] = field(default_factory=list)
    unexpected_terms: list[dict] = field(default_factory=list)  # soft signal, not a failure


def compute(case: EvalCase, original: dict[str, str], result: TailoringResult, *, live: bool) -> CaseMetrics:
    m = CaseMetrics()
    source_text = "\n".join(original.values())
    for bid, new in result.edits.items():
        old = original[bid]
        for term in case.canaries:
            if contains_term(new, term) and not contains_term(old, term):
                m.fabrications.append({"block": bid, "kind": "canary", "term": term})
        for n in sorted(bare_numbers(new) - bare_numbers(old)):
            m.fabrications.append({"block": bid, "kind": "number", "term": n})
        # Names or technologies that appear nowhere in the source resume. Reported, not
        # failed: a JD's canonical name for a synonym the resume uses is legitimate.
        for t in sorted(tech_terms(new) - tech_terms(old)):
            if not contains_term(source_text, t):
                m.unexpected_terms.append({"block": bid, "term": t})
        drift = abs(len(clean(new)) - len(clean(old))) / max(len(clean(old)), 1)
        m.max_length_drift = max(m.max_length_drift, round(drift, 3))
        if drift > LENGTH_WARN_RATIO:
            m.length_outliers.append(bid)
        m.total_chars_delta += len(clean(new)) - len(clean(old))

    before = scoring.keyword_report(source_text, result.job)
    after = scoring.keyword_report("\n".join(result.edits.get(k, v) for k, v in original.items()), result.job)
    m.coverage_before, m.coverage_after = round(before.coverage, 1), round(after.coverage, 1)
    m.ats_before, m.ats_after = result.scores_before.ats, result.scores_after.ats
    m.changes = len(result.changes)
    cov = next((v for v in result.validations if v.rule_key == "pipeline.coverage"), None)
    m.reverted = len(cov.details["reverted_blocks"]) if cov else 0
    m.gaps_reported = list(result.plan.gaps)
    if live:
        # "CPA license" or "Active CPA license" reports the CPA gap; exact match is too strict.
        m.expected_gaps_missed = [
            g for g in case.expect.live_expected_gaps
            if not any(contains_term(r, g) or contains_term(g, r) for r in result.plan.gaps)]
    return m


def failures(case: EvalCase, m: CaseMetrics, *, live: bool) -> list[str]:
    """Hard failures. Fabrication always fails; the live-only expectations apply only to
    real models because the offline provider just swaps synonyms."""
    out = []
    if m.fabrications:
        out.append("fabrication")
    if m.changes < case.expect.min_changes:
        out.append("too_few_changes")
    if live:
        e = case.expect
        if e.live_min_changes is not None and m.changes < e.live_min_changes:
            out.append("too_few_changes")
        if e.live_max_changes is not None and m.changes > e.live_max_changes:
            out.append("too_many_changes")
        if m.expected_gaps_missed:
            out.append("missed_gaps")
        if m.coverage_after + 0.05 < m.coverage_before:
            out.append("coverage_dropped")
    return sorted(set(out))
