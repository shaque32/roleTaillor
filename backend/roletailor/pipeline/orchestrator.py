"""Pipeline entry point: structure -> analyze job -> plan -> rewrite <-> validate -> score.

Deterministic code orchestrates; models fill typed slots. Rewrites that fail any gate
are retried with the reasons, then escalated one tier, then dropped in favour of the
original text, so a generation degrades to "fewer changes", never to invented ones.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from roletailor.ai.gateway import AIUnavailable, Gateway
from roletailor.documents.model import ParsedDocument
from roletailor.domain.models import (
    BlockRewrite,
    Change,
    JobAnalysis,
    ResumeStructure,
    TailoringResult,
    ValidationOutcome,
    Violation,
)
from roletailor.pipeline import scoring, stages
from roletailor.pipeline.text import clean, contains_any
from roletailor.pipeline.validation.rules import (
    RULE_VERSION,
    BlockContext,
    DocContext,
    check_block,
    check_document,
    has_gain,
    scope_length_bounds,
)

log = logging.getLogger(__name__)
MAX_ROUNDS = 3  # upper bound; routing.rewrite_max_rounds sets the actual number
BLOCKING_RULES = ("facts.numbers", "facts.terms", "facts.keywords", "facts.claims",
                  "layout.length", "authenticity.phrases", "authenticity.stuffing")
# Gates that catch invented content. A block can trip several of them at once.
FABRICATION_RULES = ("facts.numbers", "facts.terms", "facts.keywords", "facts.claims")


class TailoringPrefs(BaseModel):
    page_limit: int = 2
    tone: str | None = None
    technical_depth: str | None = None
    industry_focus: str | None = None
    ats_preference: str | None = None
    # Subscription tier lets premium users start the plan stage one tier higher.
    customer_tier: str = "free"  # free | subscription | enterprise


def tailor(
    *,
    document: ParsedDocument,
    job_text: str,
    prefs: TailoringPrefs,
    gateway: Gateway,
    source_docx: bytes | None = None,
    source_pdf: bytes | None = None,
    cached_structure: ResumeStructure | None = None,
    cached_job: JobAnalysis | None = None,
    iteration: int = 1,
    focus_block_ids: list[str] | None = None,
) -> TailoringResult:
    """Run one tailoring iteration. Pure with respect to persistence: everything to
    store comes back in the result, and every model call goes through the gateway's
    MetricsSink. `cached_structure` / `cached_job` skip the two cacheable stages.
    `focus_block_ids` limits rewriting to those blocks (targeted regeneration).
    Raises AIUnavailable when the plan cannot be produced or nothing could be verified.
    """
    it = f"it{iteration}"
    outcomes: list[ValidationOutcome] = []

    structure, degraded_s = (cached_structure, False) if cached_structure else \
        stages.structure_resume(gateway, document, f"{it}:structure_resume")
    job, degraded_j = (cached_job, False) if cached_job else \
        stages.analyze_job(gateway, job_text, f"{it}:analyze_job")
    if degraded_s or degraded_j:
        outcomes.append(ValidationOutcome(
            rule_key="pipeline.degraded", rule_version=RULE_VERSION, passed=True,
            details={"structure_heuristic": degraded_s, "job_heuristic": degraded_j}))

    scopes = stages.block_scopes(structure, document)
    pref_dict = prefs.model_dump(exclude={"customer_tier"}, exclude_none=True)
    plan = stages.plan(gateway, doc=document, structure=structure, job=job, scopes=scopes,
                       prefs=pref_dict, focus=focus_block_ids, label=f"{it}:plan")

    doc_ctx = DocContext(facts=structure.facts, job=job)
    accepted, log_by_rule, dropped, source = _rewrite_and_validate(
        gateway, document=document, plan=plan, scopes=scopes, job=job, doc_ctx=doc_ctx,
        prefs=pref_dict, it=it, focus=set(focus_block_ids or []))

    edits = {bid: r.new_text for bid, r in accepted.items()}
    page_count = None
    if source_docx is not None and edits:
        edits, page_count, page_outcome = _enforce_page_limit(source_docx, edits, document, prefs.page_limit)
        outcomes.append(page_outcome)
        accepted = {b: r for b, r in accepted.items() if b in edits}
    elif source_pdf is not None and edits:
        edits, fit_outcome = _fit_pdf_layout(source_pdf, edits)
        outcomes.append(fit_outcome)
        accepted = {b: r for b, r in accepted.items() if b in edits}

    outcomes += _rule_outcomes(log_by_rule, dropped, len(plan.block_plans))
    final_texts = {b.id: edits.get(b.id, b.text) for b in document.text_blocks()}
    bullets_by_entry = [e.bullet_block_ids for s in structure.sections for e in s.entries]
    warnings = check_document(final_texts, bullets_by_entry, doc_ctx)
    outcomes.append(ValidationOutcome(
        rule_key="authenticity.document", rule_version=RULE_VERSION, passed=True,
        score=max(0.0, 100.0 - 10 * len(warnings)), threshold=50.0,
        details={"warnings": [w.model_dump() for w in warnings]}))

    before_text = stages.resume_text(document.blocks)
    after_text = stages.resume_text(document.blocks, edits)
    before = scoring.score(before_text, job, structure, document.findings, page_limit=prefs.page_limit)
    after = scoring.score(after_text, job, structure, document.findings,
                          page_count=page_count, page_limit=prefs.page_limit)
    kw = scoring.keyword_report(after_text, job)
    feedback = stages.hiring_manager_feedback(
        gateway, job=job, resume_text=after_text,
        ats={"coverage": round(kw.coverage, 1), "matched": kw.matched, "missing": kw.missing},
        gaps=plan.gaps, label=f"{it}:feedback")

    by_id = {b.id: b for b in document.blocks}
    changes = [
        Change(block_path=bid, prior_text=by_id[bid].text, proposed_text=r.new_text, reason=r.reason,
               prioritized_keywords=[k for k in r.keywords_used if contains_any(r.new_text, [k])],
               scope=scopes.get(bid), source_stage=source.get(bid))
        for bid, r in accepted.items()
    ]
    return TailoringResult(
        structure=structure, job=job, plan=plan, changes=changes, edits=edits,
        validations=outcomes, scores_before=before, scores_after=after, feedback=feedback,
        total_cost_usd=round(gateway.total_cost_usd, 8),
    )


def _rewrite_and_validate(gateway: Gateway, *, document: ParsedDocument, plan, scopes, job,
                          doc_ctx: DocContext, prefs: dict, it: str, focus: set[str] = frozenset()):
    by_id = {b.id: b for b in document.blocks}
    plans = {bp.block_id: bp for bp in plan.block_plans}
    pending = set(plans)
    feedback: dict[str, list[str]] = {}
    accepted: dict[str, BlockRewrite] = {}
    log_by_rule: dict[str, list[Violation]] = defaultdict(list)
    verifier_down = False
    no_gain: dict[str, str] = {}
    source: dict[str, str] = {}  # which stage wrote each accepted edit
    context = {"job_title": job.title, "positioning": plan.positioning,
               "tone": prefs.get("tone"), "technical_depth": prefs.get("technical_depth")}
    router = gateway.router
    keywords = {b: bp.target_keywords for b, bp in plans.items()}
    backed = {b: [te.model_dump() for te in bp.term_evidence] for b, bp in plans.items()}
    # The summary has its own stage. It may name any job term the resume has earned, so
    # its gates are given that list in place of the planner's three keywords.
    sid = _summary_target(plans, scopes) if "summary" in router.stages else None
    if sid:
        cands = stages.summary_candidates(job, plan, document.text_blocks())
        keywords[sid] = [c["term"] for c in cands]
        backed[sid] = [{"job_term": c["term"], "resume_quote": c["resume_quote"]} for c in cands]
        whole = stages.resume_text(document.blocks)[:12000]

    def item(bid: str) -> dict:
        bp, orig = plans[bid], by_id[bid].text
        lo, hi = scope_length_bounds(len(clean(orig)), scopes[bid], doc_ctx.length_tolerance)
        return {"block_id": bid, "text": orig, "target_keywords": bp.target_keywords,
                "evidence": bp.evidence, "instruction": bp.instruction,
                "term_evidence": [te.model_dump() for te in bp.term_evidence],
                "min_chars": max(lo, 1), "max_chars": hi}

    def write(items: list[dict], rnd: int, feedback: dict) -> dict[str, BlockRewrite]:
        if not items:
            return {}
        return stages.rewrite(gateway, items=items, context=context, feedback=feedback,
                              label=f"{it}:rewrite:r{rnd}", batch_size=router.rewrite_batch_size,
                              concurrency=router.rewrite_concurrency, escalate=1 if rnd == 2 else 0)

    def draft_summary(rnd: int, reasons: list[str]) -> BlockRewrite | None:
        i = item(sid)
        try:
            d = stages.write_summary(
                gateway, original=i["text"], candidates=cands, context=context, resume=whole,
                min_chars=i["min_chars"], max_chars=i["max_chars"],
                feedback=reasons, label=f"{it}:summary:r{rnd}")
        except AIUnavailable as e:
            log.warning("summary stage failed, using the bullet writer: %s", e)
            return None
        return BlockRewrite(block_id=sid, new_text=d.new_text, keywords_used=keywords[sid],
                            reason=d.reason or "Summary now leads with what this job asks for.")

    for rnd in range(min(MAX_ROUNDS, router.rewrite_max_rounds)):
        if not pending:
            break
        order = sorted(pending, key=lambda x: list(plans).index(x))
        with ThreadPoolExecutor(max_workers=1) as pool:  # summary runs beside the bullets
            fut = pool.submit(draft_summary, rnd, feedback.get(sid, [])) if sid in pending else None
            out = write([item(b) for b in order if not (fut and b == sid)], rnd, feedback)
            summary = fut.result() if fut else None
        if summary:
            out[sid] = summary
        elif fut:
            out.update(write([item(sid)], rnd, feedback))
        by_summary_stage = {sid} if summary else set()

        failures: dict[str, list[Violation]] = {}
        candidates: dict[str, BlockRewrite] = {}
        for bid in pending:
            r = out.get(bid)
            if r is None:
                failures[bid] = [Violation(rule_key="pipeline.no_output", block_id=bid,
                                           detail="no rewrite returned for this block")]
                continue
            if clean(r.new_text) == clean(by_id[bid].text):
                continue  # model chose to keep it; nothing to validate
            if bid not in focus and not has_gain(by_id[bid].text, r.new_text, job):
                no_gain[bid] = r.new_text
                continue  # cosmetic edit: keep the original, do not spend a verify call
            ctx = BlockContext(block_id=bid, original=by_id[bid].text, scope=scopes[bid],
                               target_keywords=keywords[bid],
                               supported_terms=[te["job_term"] for te in backed[bid]])
            v = check_block(ctx, r.new_text, doc_ctx)
            if v:
                failures[bid] = v
            else:
                candidates[bid] = r

        if candidates:
            pairs = [{"block_id": b, "original": by_id[b].text, "rewritten": r.new_text,
                      "claimed_equivalences": [te for te in backed[b]
                                               if contains_any(r.new_text, [te["job_term"]])
                                               and not contains_any(by_id[b].text, [te["job_term"]])]}
                     for b, r in candidates.items()]
            try:
                check = stages.verify_claims(gateway, pairs=pairs, facts=doc_ctx.facts,
                                             label=f"{it}:verify_claims:r{rnd}")
                verdicts = {v.block_id: v for v in check.results}
            except AIUnavailable:
                verifier_down, verdicts = True, {}
            for b, r in candidates.items():
                v = verdicts.get(b)
                if v is not None and v.supported:
                    accepted[b] = r
                    source[b] = "summary" if b in by_summary_stage else "rewrite"
                else:
                    why = (f"unsupported claims: {v.unsupported_claims}" if v
                           else "claim verifier unavailable" if verifier_down else "not verified")
                    failures[b] = [Violation(rule_key="facts.claims", block_id=b, detail=why)]

        for vs in failures.values():
            for v in vs:
                log_by_rule[v.rule_key].append(v)
        feedback = {b: [v.detail for v in vs] for b, vs in failures.items()}
        pending = set(failures)
        if verifier_down:
            break  # without a verifier nothing new can be accepted

    if verifier_down and not accepted:
        raise AIUnavailable(f"{it}:verify_claims", "claim verifier unavailable")
    for bid, proposed in no_gain.items():
        if bid not in accepted:  # a later round may have produced a useful edit
            log_by_rule["value.no_gain"].append(Violation(
                rule_key="value.no_gain", block_id=bid, severity="warn",
                detail=f"kept original; proposed edit added nothing for this job: {proposed[:300]}"))
    return accepted, log_by_rule, sorted(pending), source


def _summary_target(plans: dict, scopes: dict[str, str]) -> str | None:
    """The planned summary block, when there is exactly one, so the summary stage's
    output has an unambiguous home. Otherwise summaries go to the bullet writer."""
    targets = [b for b in plans if scopes.get(b) == "summary"]
    return targets[0] if len(targets) == 1 else None


# Above this share of edits lost to layout, content wins: keep every edit and let the
# renderer fall back to the ATS template instead of the original PDF layout.
PDF_FIT_MAX_DROP_RATIO = 0.5


def _fit_pdf_layout(source_pdf: bytes, edits: dict[str, str]) -> tuple[dict[str, str], ValidationOutcome]:
    """Keep the original PDF layout: revert edits that cannot be drawn in their own lines
    (overflow, missing glyphs, mixed styles). The page count can never change in place.
    If more than half the edits would be lost, keep them all; rendering then uses the
    template, which is recorded on the generated version."""
    def outcome(mode: str, reverted: dict[str, str], unfit: dict[str, str]) -> ValidationOutcome:
        # `reverted` lists only edits actually removed; `unfit` explains a template choice.
        return ValidationOutcome(
            rule_key="layout.pdf_in_place", rule_version=RULE_VERSION, passed=True,
            score=round(100.0 * (1 - len(reverted) / len(edits)), 1),
            details={"mode": mode, "reverted": reverted, "unfit": unfit})

    try:
        from roletailor.documents import fit_pdf_edits

        kept, dropped = fit_pdf_edits(source_pdf, edits)
    except Exception as e:  # noqa: BLE001 - layout fitting is best effort; never fail a generation
        log.warning("PDF layout fit skipped: %s", e)
        return edits, ValidationOutcome(
            rule_key="layout.pdf_in_place", rule_version=RULE_VERSION, passed=True,
            details={"skipped": str(e)[:200]})
    if len(dropped) > PDF_FIT_MAX_DROP_RATIO * len(edits):
        return edits, outcome("template", {}, dropped)
    return kept, outcome("in_place", dropped, {})


def _enforce_page_limit(source_docx: bytes, edits: dict[str, str], document: ParsedDocument,
                        page_limit: int) -> tuple[dict[str, str], int | None, ValidationOutcome]:
    """Render and count pages; if edits push past the limit, revert the edits that grew
    the most until it fits. If the original was already over the limit, report it."""
    try:
        from roletailor.documents import apply_block_edits, count_pdf_pages, docx_to_pdf

        def pages(e: dict[str, str]) -> int:
            return count_pdf_pages(docx_to_pdf(apply_block_edits(source_docx, e)))

        n = pages(edits)
    except Exception as e:  # noqa: BLE001 - rendering is best effort; never fail a generation
        log.warning("page check skipped: %s", e)
        return edits, None, ValidationOutcome(
            rule_key="layout.page_limit", rule_version=RULE_VERSION, passed=True,
            details={"skipped": str(e)[:200]})

    by_id = {b.id: b for b in document.blocks}
    reverted: list[str] = []
    while n > page_limit and edits:
        growth = sorted(edits, key=lambda b: len(edits[b]) - len(by_id[b].text), reverse=True)
        if len(edits[growth[0]]) <= len(by_id[growth[0]].text):
            break  # no growing edits left; the original itself is too long
        drop = growth[:max(1, len(growth) // 3)]
        reverted += drop
        edits = {b: t for b, t in edits.items() if b not in drop}
        n = pages(edits) if edits else pages({})
    return edits, n, ValidationOutcome(
        rule_key="layout.page_limit", rule_version=RULE_VERSION, passed=n <= page_limit,
        score=float(n), threshold=float(page_limit),
        details={"pages": n, "reverted_blocks": reverted})


def _rule_outcomes(log_by_rule: dict[str, list[Violation]], dropped: list[str],
                   planned: int) -> list[ValidationOutcome]:
    """One validation_results row per gate: how often it fired, and whether any block
    still failed it at the end (those blocks kept their original text)."""
    final_fail = set(dropped)
    out = []
    for rule in BLOCKING_RULES:
        vs = log_by_rule.get(rule, [])
        still = sorted({v.block_id for v in vs if v.block_id in final_fail})
        out.append(ValidationOutcome(
            rule_key=rule, rule_version=RULE_VERSION, passed=True,
            score=round(100.0 * (1 - len({v.block_id for v in vs}) / planned), 2) if planned else 100.0,
            threshold=None,
            details={"violations": [v.model_dump() for v in vs[:50]],
                     "reverted_to_original": still}))
    skipped = log_by_rule.get("value.no_gain", [])
    out.append(ValidationOutcome(
        rule_key="value.no_gain", rule_version=RULE_VERSION, passed=True,
        score=round(100.0 * (1 - len(skipped) / planned), 2) if planned else 100.0,
        details={"kept_original": [v.block_id for v in skipped],
                 "proposals": {v.block_id: v.detail.split(": ", 1)[-1] for v in skipped}}))
    # Distinct blocks flagged by any fabrication gate: per-rule counts overlap, so the
    # fabrication attempt rate is computed from this row, never by summing rules.
    fabricated = {v.block_id for rule in FABRICATION_RULES for v in log_by_rule.get(rule, [])}
    out.append(ValidationOutcome(
        rule_key="pipeline.fabrication", rule_version=RULE_VERSION, passed=True,
        score=round(100.0 * (1 - len(fabricated) / planned), 2) if planned else 100.0,
        details={"flagged_blocks": len(fabricated), "planned_blocks": planned,
                 "reverted_blocks": len(fabricated & final_fail)}))
    out.append(ValidationOutcome(
        rule_key="pipeline.coverage", rule_version=RULE_VERSION, passed=True,
        details={"planned_blocks": planned, "reverted_blocks": dropped}))
    return out
