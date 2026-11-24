"""Pipeline entry point. Implementation in progress; the signature is the contract."""

from __future__ import annotations

from pydantic import BaseModel

from roletailor.documents.model import ParsedDocument
from roletailor.domain.models import JobAnalysis, ResumeStructure, TailoringResult


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
    gateway,  # roletailor.ai.gateway.Gateway
    source_docx: bytes | None = None,
    cached_structure: ResumeStructure | None = None,
    cached_job: JobAnalysis | None = None,
    iteration: int = 1,
    focus_block_ids: list[str] | None = None,
) -> TailoringResult:
    """Run analyze -> plan -> rewrite -> validate -> score for one iteration.

    Pure with respect to persistence: everything to store comes back in the result,
    and every model call is reported through the gateway's MetricsSink.
    `cached_structure` / `cached_job` skip the two cacheable stages.
    `focus_block_ids` limits rewriting to those blocks (targeted regeneration).
    """
    raise NotImplementedError
