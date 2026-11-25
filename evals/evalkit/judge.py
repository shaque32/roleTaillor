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

RUBRIC_VERSION = "4"
SYSTEM = """You review resume edits made by an automated tailoring tool. You get the job
description, the original text of each edited block, and the new text. Judge only what
the edits changed. Be strict and consistent; do not reward length.

Score each criterion from 1 (bad) to 5 (excellent):
- truthfulness: every claim in the new text is supported by the original resume. Any
  new tool, employer, credential, number, scope, or seniority not in the original is a 1.
  Rewording that implies more ownership or impact than the original shows is at most 3.
- relevance: how well the edits captured the honest opportunities to fit this job.
  First list, for yourself, where the original resume already shows work the job asks
  for but in different words, buried, or missing from the summary. Then score how many
  of those the edits surfaced in the job's wording. 5: the important ones are captured
  and no edit is pointless. 3: about half captured, or good edits mixed with reorderings
  that do nothing. 1: the edits are cosmetic, or clear matches were left unsurfaced.
  A match means the resume shows the same thing or a specific instance of it (Terraform
  modules for infrastructure as code). A different audience, scale, level, or credential
  is not a match (an executive committee is not the board; CI is not CD), and surfacing
  it would be dishonest: never list those as missed.
  Do not mark down for requirements the candidate has not met; leaving those out is
  correct. A resume with nothing honest to improve and no edits scores 5.
- readability: the new text is clear, specific, grammatical, and free of filler or
  AI-sounding phrases.
- voice: the edits keep the candidate's tone and the original structure.
In unsupported_claims, quote only text from the new version that states something the
original resume does not support. Leave it empty when every edit is supported; do not
list edits that are merely weaker, awkward, or pointless (score those under relevance,
readability, or voice). In missed_opportunities, list up to 4 specific matches the
edits should have surfaced and did not, each as "resume says X; job asks for Y". Reply
with JSON only."""


class JudgeVerdict(BaseModel):
    truthfulness: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    readability: int = Field(ge=1, le=5)
    voice: int = Field(ge=1, le=5)
    unsupported_claims: list[str] = Field(default_factory=list)
    missed_opportunities: list[str] = Field(default_factory=list)
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
