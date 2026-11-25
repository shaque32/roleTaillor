"""Deterministic validation gates. A model never gets the last word on truthfulness:
every rewrite must pass these checks, then the claim verifier, or it is dropped.

Each rule has a stable key and version that land in validation_results.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from roletailor.domain.models import FactInventory, JobAnalysis, Violation
from roletailor.pipeline.text import (
    bare_numbers,
    clean,
    contains_any,
    contains_term,
    count_term,
    first_word,
    norm,
    tech_terms,
)

RULE_VERSION = "2"

BANNED_PHRASES = [
    "results-driven", "results driven", "passionate", "dynamic professional", "synergy",
    "synergies", "spearheaded", "leveraged", "utilized", "cutting-edge", "cutting edge",
    "fast-paced", "fast paced", "proven track record", "seamlessly", "go-getter", "delve",
    "game-changer", "game changer", "best-in-class", "thought leader", "rockstar", "ninja",
    "world-class", "detail-oriented",
]


@dataclass
class BlockContext:
    block_id: str
    original: str
    scope: str  # "bullet" | "summary" | "skills"
    target_keywords: list[str] = field(default_factory=list)


@dataclass
class DocContext:
    facts: FactInventory
    job: JobAnalysis
    length_tolerance: float = 0.15

    def fact_terms(self) -> list[str]:
        f = self.facts
        return [*f.tools, *f.skills, *f.companies, *f.certifications, *f.titles, *f.degrees]


def check_block(ctx: BlockContext, new_text: str, doc: DocContext) -> list[Violation]:
    out: list[Violation] = []
    new, orig = clean(new_text), clean(ctx.original)
    bid = ctx.block_id

    # facts.numbers: no new numbers anywhere, ever.
    added_numbers = bare_numbers(new) - bare_numbers(orig)
    if added_numbers:
        out.append(Violation(rule_key="facts.numbers", block_id=bid,
                             detail=f"adds numbers not in the original: {sorted(added_numbers)}"))

    # facts.terms: proper nouns / technologies must come from this block, or from the
    # fact inventory for summary and skills lines.
    allowed_pool = orig if ctx.scope == "bullet" else orig + "\n" + "\n".join(doc.fact_terms())
    invented = sorted(t for t in tech_terms(new) - tech_terms(orig)
                      if not contains_term(allowed_pool, t) and not _is_jd_synonym_of_orig(t, orig, doc))
    if invented:
        out.append(Violation(rule_key="facts.terms", block_id=bid,
                             detail=f"introduces names or technologies not in the original: {invented}"))

    # facts.keywords: a JD keyword may appear only if the original supports it.
    for k in doc.job.keywords:
        forms = [k.term, *k.synonyms]
        if contains_any(new, forms) and not contains_any(allowed_pool, forms):
            out.append(Violation(rule_key="facts.keywords", block_id=bid,
                                 detail=f"adds job keyword '{k.term}' that the original does not show"))

    # layout.length: stay inside the length budget so lines and pages do not shift.
    lo, hi = length_bounds(len(orig), doc.length_tolerance)
    if not lo <= len(new) <= hi:
        out.append(Violation(rule_key="layout.length", block_id=bid,
                             detail=f"length {len(new)} outside {lo}-{hi} characters"))

    # authenticity.phrases
    lowered = new.lower()
    hits = [p for p in BANNED_PHRASES if p in lowered and p not in orig.lower()]
    if hits:
        out.append(Violation(rule_key="authenticity.phrases", block_id=bid,
                             detail=f"uses generic or AI-sounding phrases: {hits}"))

    # authenticity.stuffing: no keyword twice in one line, at most 3 JD keywords added.
    added_kw = [k.term for k in doc.job.keywords
                if contains_any(new, [k.term, *k.synonyms]) and not contains_any(orig, [k.term, *k.synonyms])]
    repeated = [k.term for k in doc.job.keywords if count_term(new, k.term) > max(1, count_term(orig, k.term))]
    if len(added_kw) > 3 or repeated:
        out.append(Violation(rule_key="authenticity.stuffing", block_id=bid,
                             detail=f"keyword stuffing: added={added_kw} repeated={repeated}"))

    if not new.strip():
        out.append(Violation(rule_key="layout.length", block_id=bid, detail="empty rewrite"))
    return out


def _is_jd_synonym_of_orig(term: str, orig: str, doc: DocContext) -> bool:
    """Allow the JD's canonical name for something the original already names via a
    synonym, e.g. original "ML" -> new "machine learning"."""
    for k in doc.job.keywords:
        forms = [k.term, *k.synonyms]
        if any(contains_term(term, f) or contains_term(f, term) for f in forms) and contains_any(orig, forms):
            return True
    return False


def length_bounds(n: int, tol: float) -> tuple[int, int]:
    return int(n * (1 - tol)) - 8, int(n * (1 + tol)) + 8


def check_document(texts: dict[str, str], bullets_by_entry: list[list[str]],
                   doc: DocContext) -> list[Violation]:
    """Cross-block authenticity checks on the final text. Warnings, not blockers."""
    out: list[Violation] = []
    full = "\n".join(texts.values())
    for k in doc.job.keywords:
        n = count_term(full, k.term)
        if n > 4:
            out.append(Violation(rule_key="authenticity.density", detail=f"'{k.term}' appears {n} times",
                                 severity="warn"))
    for entry in bullets_by_entry:
        verbs = [first_word(texts[b]) for b in entry if b in texts]
        for v in {x for x in verbs if x and verbs.count(x) > 2}:
            out.append(Violation(rule_key="authenticity.repetition",
                                 detail=f"{verbs.count(v)} bullets in one role start with '{v}'",
                                 severity="warn"))
    return out


def has_gain(original: str, new_text: str, job: JobAnalysis) -> bool:
    """True when an edit measurably helps this job: it uses a job keyword in the job's own
    wording that the line lacked, shows one more job keyword, or moves the first job
    keyword earlier. Edits that only reshuffle or reword are noise in the candidate's
    review and a risk to their meaning, so the pipeline keeps the original instead.
    With no job keywords to measure against, every edit is allowed through."""
    if not job.keywords:
        return True
    if any(contains_term(new_text, k.term) and not contains_term(original, k.term) for k in job.keywords):
        return True

    def shown(text: str) -> int:
        return sum(contains_any(text, [k.term, *k.synonyms]) for k in job.keywords)

    def first(text: str) -> int | None:
        t = norm(text)
        hits = [m.start() for k in job.keywords for f in [k.term, *k.synonyms] if norm(f)
                for m in [re.search(rf"(?<![\w+#]){re.escape(norm(f))}(?![\w+#])", t)] if m]
        return min(hits) if hits else None

    if shown(new_text) > shown(original):
        return True
    a, b = first(original), first(new_text)
    return a is not None and b is not None and b < a - 3
