"""The model-backed stages. Each one builds a compact payload, calls the gateway with a
versioned prompt and a typed output, and sanitizes the result against the source
document so a bad model answer cannot widen what later stages are allowed to do."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from roletailor.ai.gateway import AIUnavailable, Gateway
from roletailor.documents.model import Block, ParsedDocument
from roletailor.domain.models import (
    BlockPlan,
    BlockRewrite,
    ClaimCheck,
    FactInventory,
    HiringManagerFeedback,
    JobAnalysis,
    ResumeStructure,
    RewriteBatch,
    TailoringPlan,
)
from roletailor.pipeline import heuristics
from roletailor.pipeline.text import clean, contains_term

log = logging.getLogger(__name__)
EDITABLE_SCOPES = {"bullet", "summary", "skills"}


# --------------------------------------------------------------------------- structure


def structure_resume(gw: Gateway, doc: ParsedDocument, label: str) -> tuple[ResumeStructure, bool]:
    """Returns (structure, degraded). Degraded means the deterministic fallback ran."""
    blocks = doc.text_blocks()
    payload = {"blocks": [{"id": b.id, "text": b.text, "style": b.style_name,
                           "list": b.is_list_item, "heading": b.is_heading} for b in blocks]}
    try:
        s = gw.run(stage="structure_resume", label=label, prompt_key="structure_resume",
                   payload=payload, output=ResumeStructure)
    except AIUnavailable as e:
        log.warning("structure_resume degraded to heuristics: %s", e)
        return heuristics.structure_from_blocks(doc.blocks), True
    return _sanitize_structure(s, doc), False


def _sanitize_structure(s: ResumeStructure, doc: ParsedDocument) -> ResumeStructure:
    ids = {b.id for b in doc.blocks}
    for sec in s.sections:
        sec.block_ids = [i for i in sec.block_ids if i in ids]
        if sec.heading_block_id not in ids:
            sec.heading_block_id = None
        for e in sec.entries:
            e.header_block_ids = [i for i in e.header_block_ids if i in ids]
            e.bullet_block_ids = [i for i in e.bullet_block_ids if i in ids]
    s.sections = [sec for sec in s.sections if sec.block_ids]
    # The fact inventory is a whitelist for later checks, so keep only entries that
    # literally occur in the resume, then add deterministic extractions.
    text = "\n".join(b.text for b in doc.blocks)
    f = s.facts
    det = heuristics.structure_from_blocks(doc.blocks).facts
    s.facts = FactInventory(**{
        name: sorted({x for x in getattr(f, name) if x and contains_term(text, x)} | set(getattr(det, name)))
        for name in FactInventory.model_fields
    })
    return s


# --------------------------------------------------------------------------- job


def analyze_job(gw: Gateway, job_text: str, label: str) -> tuple[JobAnalysis, bool]:
    try:
        job = gw.run(stage="analyze_job", label=label, prompt_key="analyze_job",
                     payload={"job_text": clean(job_text)[:20000]}, output=JobAnalysis)
    except AIUnavailable as e:
        log.warning("analyze_job degraded to heuristics: %s", e)
        return heuristics.job_from_text(job_text), True
    seen, kws = set(), []
    for k in job.keywords:
        key = k.term.strip().lower()
        if key and key not in seen:
            seen.add(key)
            kws.append(k)
    job.keywords = kws[:35]
    return job, False


# --------------------------------------------------------------------------- plan


def block_scopes(structure: ResumeStructure, doc: ParsedDocument) -> dict[str, str]:
    """Which blocks may be rewritten and how. Headings, contact details, entry header
    lines (company, title, dates), education, and certifications are never edited."""
    editable = {b.id for b in doc.blocks if b.editable and b.text.strip()}
    scopes: dict[str, str] = {}
    for sec in structure.sections:
        if sec.kind == "summary":
            for i in sec.block_ids:
                if i != sec.heading_block_id:
                    scopes[i] = "summary"
        elif sec.kind == "skills":
            for i in sec.block_ids:
                if i != sec.heading_block_id:
                    scopes[i] = "skills"
        elif sec.kind in ("experience", "projects", "achievements"):
            headers = {h for e in sec.entries for h in e.header_block_ids}
            bullets = {b for e in sec.entries for b in e.bullet_block_ids}
            for i in sec.block_ids:
                if i == sec.heading_block_id or i in headers:
                    continue
                if not sec.entries or i in bullets:
                    scopes[i] = "bullet"
    return {i: s for i, s in scopes.items() if i in editable}


def plan(gw: Gateway, *, doc: ParsedDocument, structure: ResumeStructure, job: JobAnalysis,
         scopes: dict[str, str], prefs: dict, focus: list[str] | None, label: str) -> TailoringPlan:
    by_id = {b.id: b for b in doc.blocks}
    payload = {
        "job": job.model_dump(exclude_none=True),
        "resume": {
            "sections": [{"kind": s.kind, "title": s.title,
                          "blocks": [{"id": i, "text": by_id[i].text, "editable": i in scopes}
                                     for i in s.block_ids if i in by_id]}
                         for s in structure.sections],
            "facts": structure.facts.model_dump(),
        },
        "evidence": heuristics.keyword_evidence(job, doc.text_blocks()),
        "preferences": prefs,
        "focus_block_ids": focus or [],
    }
    p = gw.run(stage="plan", label=label, prompt_key="plan", payload=payload, output=TailoringPlan)
    if (gw.router.plan_escalate_on_low_confidence and p.confidence < 0.6
            and any(bp.action == "rewrite" for bp in p.block_plans)):
        # Optional (routing.plan_escalate_on_low_confidence): re-plan one tier higher and
        # keep the better-confidence plan. Never for a plan with nothing to rewrite: a
        # larger model cannot create evidence for a poor match, it only costs more.
        try:
            p2 = gw.run(stage="plan", label=label, prompt_key="plan", payload=payload,
                        output=TailoringPlan, escalate=1)
            p = p2 if p2.confidence >= p.confidence else p
        except AIUnavailable:
            pass
    return _sanitize_plan(p, job, scopes, focus, texts={b.id: b.text for b in doc.text_blocks()})


# Named tools and credentials must appear in the resume literally. Only skills, domains,
# and practices can be claimed through a quote ("Terraform modules" shows
# "infrastructure as code"); "has a CPA" or "used Snowflake" cannot be argued into being.
QUOTABLE_CATEGORIES = {"skill", "domain", "soft", "other"}


def _valid_term_evidence(bp: BlockPlan, job: JobAnalysis, scope: str, texts: dict[str, str]) -> list:
    by_term = {k.term.lower(): k for k in job.keywords}
    own = clean(texts.get(bp.block_id, "")).lower()
    whole = clean("\n".join(texts.values())).lower()
    keep, seen = [], set()
    for te in bp.term_evidence:
        k = by_term.get(te.job_term.strip().lower())
        quote = clean(te.resume_quote).lower()
        if k is None or k.category not in QUOTABLE_CATEGORIES or len(quote) < 4 or k.term in seen:
            continue
        # A bullet may only lean on its own words; the summary and skills lines may
        # lean on anything the resume says.
        if quote in (own if scope == "bullet" else whole):
            te.job_term = k.term
            keep.append(te)
            seen.add(k.term)
    return keep[:3]


def _sanitize_plan(p: TailoringPlan, job: JobAnalysis, scopes: dict[str, str],
                   focus: list[str] | None, texts: dict[str, str] | None = None) -> TailoringPlan:
    terms = {k.term.lower(): k.term for k in job.keywords}
    keep: list[BlockPlan] = []
    seen: set[str] = set()
    for bp in p.block_plans:
        if bp.action != "rewrite" or bp.block_id not in scopes or bp.block_id in seen:
            continue
        if focus and bp.block_id not in focus:
            continue
        seen.add(bp.block_id)
        bp.target_keywords = [terms[t.lower()] for t in bp.target_keywords if t.lower() in terms][:3]
        bp.term_evidence = _valid_term_evidence(bp, job, scopes[bp.block_id], texts) if texts else []
        keep.append(bp)
    if focus:  # user-requested blocks the planner skipped still get a light pass
        keep += [BlockPlan(block_id=b, instruction="Improve clarity and relevance to the job.")
                 for b in focus if b in scopes and b not in seen]
    p.block_plans = keep
    p.gaps = [g for g in p.gaps if g.lower() in terms]
    return p


# --------------------------------------------------------------------------- rewrite


def rewrite(gw: Gateway, *, items: list[dict], context: dict, feedback: dict[str, list[str]],
            label: str, batch_size: int, concurrency: int, escalate: int = 0) -> dict[str, BlockRewrite]:
    """Rewrite blocks in parallel batches. A failed batch returns nothing for its
    blocks; the caller treats them as failed and may retry or keep the original."""
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]

    def run(i: int, batch: list[dict]) -> list[BlockRewrite]:
        fb = {b["block_id"]: feedback[b["block_id"]] for b in batch if b["block_id"] in feedback}
        payload = {**context, "blocks": batch, **({"feedback": fb} if fb else {})}
        try:
            out = gw.run(stage="rewrite", label=f"{label}b{i}", prompt_key="rewrite",
                         payload=payload, output=RewriteBatch, escalate=escalate)
            return out.rewrites
        except AIUnavailable as e:
            log.warning("rewrite batch %s failed: %s", i, e)
            return []

    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(batches)))) as pool:
        results = list(pool.map(lambda a: run(*a), enumerate(batches)))
    originals = {b["block_id"]: b["text"] for b in items}
    out = {r.block_id: r for rs in results for r in rs if r.block_id in originals}
    for bid, r in out.items():
        r.new_text = _match_ending(originals[bid], r.new_text)
    return out


def _match_ending(original: str, new: str) -> str:
    """Keep the original's closing full stop (or lack of one). Models drop or add it at
    random, which shows up as noise in the diff the candidate reviews."""
    o, n = original.rstrip(), new.rstrip()
    if not n or o.endswith(".") == n.endswith("."):
        return new
    return n + "." if o.endswith(".") else n.rstrip(".")


def verify_claims(gw: Gateway, *, pairs: list[dict], facts: FactInventory, label: str) -> ClaimCheck:
    payload = {"pairs": pairs, "facts": facts.model_dump()}
    return gw.run(stage="verify_claims", label=label, prompt_key="verify_claims",
                  payload=payload, output=ClaimCheck)


# --------------------------------------------------------------------------- feedback


def hiring_manager_feedback(gw: Gateway, *, job: JobAnalysis, resume_text: str, ats: dict,
                            gaps: list[str], label: str) -> HiringManagerFeedback | None:
    payload = {"job": job.model_dump(exclude_none=True), "resume_text": resume_text[:24000],
               "ats": ats, "gaps": gaps}
    try:
        return gw.run(stage="feedback", label=label, prompt_key="feedback", payload=payload,
                      output=HiringManagerFeedback)
    except AIUnavailable as e:
        log.warning("feedback unavailable: %s", e)
        return None


def resume_text(blocks: list[Block], edits: dict[str, str] | None = None) -> str:
    edits = edits or {}
    return "\n".join(edits.get(b.id, b.text) for b in blocks if b.text.strip())
