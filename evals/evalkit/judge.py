"""LLM judge for live evals. Scores the tailored resume against the original and the job
on a fixed rubric. The deterministic checks in metrics.py stay the gate for fabrication;
the judge measures what they cannot: relevance, readability, and whether the voice held.

The judge runs on a model outside the pipeline's serving path being compared (Sonnet by
default, set with --judge-model) so it does not grade its own planning.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from roletailor.ai.gateway import _strip_fences
from roletailor.ai.providers.base import LLMRequest, ModelSpec, ProviderError

RUBRIC_VERSION = "1"
SYSTEM = """You review resume edits made by an automated tailoring tool. You get the job
description, the original text of each edited block, and the new text. Judge only what
the edits changed. Be strict and consistent; do not reward length.

Score each criterion from 1 (bad) to 5 (excellent):
- truthfulness: every claim in the new text is supported by the original resume. Any
  new tool, employer, credential, number, scope, or seniority not in the original is a 1.
  Rewording that implies more ownership or impact than the original shows is at most 3.
- relevance: the edits make the resume read as a better fit for this job, using the job's
  own terms where the candidate's experience genuinely matches.
- readability: the new text is clear, specific, grammatical, and free of filler or
  AI-sounding phrases.
- voice: the edits keep the candidate's tone and the original structure.
If there are no edits, score relevance by whether leaving the resume alone was right
for this job (5 if the job is a poor fit or nothing could be honestly improved).

List each unsupported claim you find verbatim in unsupported_claims. Reply with JSON only."""


class JudgeVerdict(BaseModel):
    truthfulness: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    readability: int = Field(ge=1, le=5)
    voice: int = Field(ge=1, le=5)
    unsupported_claims: list[str] = Field(default_factory=list)
    rationale: str = ""


def judge(provider, spec: ModelSpec, *, job: str, resume_text: str, edits: list[dict]) -> tuple[dict, float]:
    """Returns (verdict dict, cost in USD). Raises ProviderError on failure."""
    payload = {"job_description": job[:12000], "original_resume": resume_text[:16000], "edits": edits}
    req = LLMRequest(prompt_key="eval_judge", system=SYSTEM,
                     user=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                     json_schema=JudgeVerdict.model_json_schema(), max_tokens=3000, timeout_s=90)
    resp = provider.complete(spec, req)
    try:
        v = JudgeVerdict.model_validate_json(_strip_fences(resp.text))
    except ValueError as e:
        raise ProviderError(f"judge returned invalid JSON: {e}", code="schema_invalid") from e
    return {**v.model_dump(), "rubric_version": RUBRIC_VERSION, "model": spec.model}, spec.cost(resp.usage)
