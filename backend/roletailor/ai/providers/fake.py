"""Deterministic offline provider for tests, local development, and CI evals.

It answers each prompt with the deterministic heuristics, so the whole pipeline
(routing, validation, persistence, rendering) runs without network or keys. Token
counts are estimated from text length, so cost reports use the real price table.
"""

from __future__ import annotations

import json
import re

from roletailor.ai.providers.base import LLMRequest, LLMResponse, ModelSpec, ProviderError, Usage
from roletailor.documents.model import Block
from roletailor.domain.models import (
    BlockPlan,
    BlockRewrite,
    ClaimCheck,
    ClaimVerdict,
    HiringManagerFeedback,
    JobAnalysis,
    RewriteBatch,
    SummaryDraft,
    TailoringPlan,
)
from roletailor.pipeline import heuristics
from roletailor.pipeline.text import contains_term, tech_terms


class FakeProvider:
    name = "fake"

    def __init__(self, fail_models: set[str] | None = None):
        self.fail_models = fail_models or set()
        self.calls: list[tuple[str, str]] = []

    def complete(self, spec: ModelSpec, req: LLMRequest) -> LLMResponse:
        self.calls.append((spec.model, req.prompt_key))
        if spec.model in self.fail_models:
            raise ProviderError("simulated outage", code="http_503")
        payload = json.loads(req.user.split("\n\nYour previous reply", 1)[0])
        handler = getattr(self, f"_{req.prompt_key}")
        text = handler(payload).model_dump_json()
        usage = Usage(input_tokens=(len(req.system) + len(req.user)) // 4,
                      output_tokens=len(text) // 4)
        return LLMResponse(text=text, usage=usage, latency_ms=1)

    # Handlers -------------------------------------------------------------

    def _structure_resume(self, p: dict):
        blocks = [Block(id=b["id"], text=b["text"], style_name=b.get("style"),
                        is_list_item=b.get("list", False), is_heading=b.get("heading", False))
                  for b in p["blocks"]]
        return heuristics.structure_from_blocks(blocks)

    def _analyze_job(self, p: dict) -> JobAnalysis:
        return heuristics.job_from_text(p["job_text"])

    def _plan(self, p: dict) -> TailoringPlan:
        """Target a JD keyword in a block only when the block already uses one of its
        synonyms, so the fake rewrite is a faithful terminology alignment."""
        job = JobAnalysis.model_validate(p["job"])
        plans, used = [], set()
        texts = {b["id"]: b["text"] for s in p["resume"]["sections"] for b in s["blocks"] if b["editable"]}
        for bid, text in texts.items():
            targets = [k.term for k in job.keywords if k.term not in used
                       and not contains_term(text, k.term)
                       and any(contains_term(text, s) for s in k.synonyms)][:2]
            if targets:
                used.update(targets)
                plans.append(BlockPlan(block_id=bid, target_keywords=targets,
                                       evidence="uses a synonym", instruction="Use the job's term."))
        evidence = p["evidence"]
        gaps = [k.term for k in job.keywords if not evidence.get(k.term)]
        return TailoringPlan(positioning="Align terminology with the role.", block_plans=plans,
                             gaps=gaps, confidence=0.8)

    def _rewrite(self, p: dict) -> RewriteBatch:
        job_kw = {}
        out = []
        for b in p["blocks"]:
            text = b["text"]
            used = []
            for term in b["target_keywords"]:
                for syn in job_kw.get(term, _synonyms(term)):
                    pattern = rf"(?<![\w+#]){re.escape(syn)}(?![\w+#])"
                    if re.search(pattern, text):
                        text = re.sub(pattern, term, text, count=1)
                        used.append(term)
                        break
            out.append(BlockRewrite(block_id=b["block_id"], new_text=text,
                                    reason="Uses the job's terminology." if used else "kept: no supported improvement",
                                    keywords_used=used))
        return RewriteBatch(rewrites=out)

    def _summary(self, p: dict) -> SummaryDraft:
        """Swap in the job's term where the summary already uses one of its synonyms."""
        b = {"block_id": "s", "text": p["summary"],
             "target_keywords": [c["term"] for c in p["candidates"]][:3]}
        r = self._rewrite({"blocks": [b]}).rewrites[0]
        return SummaryDraft(new_text=r.new_text, terms_used=r.keywords_used, reason=r.reason)

    def _verify_claims(self, p: dict) -> ClaimCheck:
        res = []
        for pair in p["pairs"]:
            added = tech_terms(pair["rewritten"]) - tech_terms(pair["original"])
            res.append(ClaimVerdict(block_id=pair["block_id"], supported=not added,
                                    unsupported_claims=sorted(added)))
        return ClaimCheck(results=res)

    def _feedback(self, p: dict) -> HiringManagerFeedback:
        cov = float(p["ats"]["coverage"])
        return HiringManagerFeedback(
            overall=round(cov * 0.8 + 10, 1), technical_alignment=round(cov, 1), leadership=55,
            domain_alignment=round(cov * 0.9, 1), communication=70,
            interview_likelihood="high" if cov > 75 else "moderate" if cov > 45 else "low",
            strengths=[f"Shows {k}" for k in p["ats"]["matched"][:3]],
            weaknesses=[f"No evidence of {g}" for g in p["gaps"][:3]],
            suggested_improvements=[f"Add real experience with {g} if you have it" for g in p["gaps"][:3]],
            competitive_positioning="Simulated offline review.")


def _synonyms(term: str) -> list[str]:
    from roletailor.pipeline.lexicon import SYNONYMS

    return SYNONYMS.get(term, [])
