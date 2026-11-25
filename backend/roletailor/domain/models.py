"""Typed contracts between pipeline stages, persistence, and the API.

Every LLM stage reads and writes one of these models, so each stage can be
cached, validated, evaluated, and swapped to a different model independently.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SectionKind = Literal[
    "header", "summary", "experience", "education", "skills", "certifications",
    "projects", "achievements", "other",
]

# --------------------------------------------------------------------------
# Resume structure (stage: structure_resume). Stored in resume_versions.content.
# --------------------------------------------------------------------------


class ExperienceEntry(BaseModel):
    company: str
    title: str
    location: str | None = None
    start: str | None = None
    end: str | None = None
    header_block_ids: list[str] = Field(default_factory=list)
    bullet_block_ids: list[str] = Field(default_factory=list)


class Section(BaseModel):
    kind: SectionKind
    title: str
    heading_block_id: str | None = None
    block_ids: list[str] = Field(default_factory=list)
    entries: list[ExperienceEntry] = Field(default_factory=list)


class FactInventory(BaseModel):
    """Everything the candidate actually claims. The anti-fabrication gate checks
    rewritten text against this inventory plus the original block text."""

    companies: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    degrees: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)


class Contact(BaseModel):
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)


class ResumeStructure(BaseModel):
    contact: Contact = Field(default_factory=Contact)
    sections: list[Section] = Field(default_factory=list)
    facts: FactInventory = Field(default_factory=FactInventory)
    seniority: str | None = None


# --------------------------------------------------------------------------
# Job analysis (stage: analyze_job). Stored in job_postings.structured_requirements.
# --------------------------------------------------------------------------


class Keyword(BaseModel):
    term: str
    importance: Literal["must", "should", "nice"] = "should"
    category: Literal["tool", "skill", "domain", "soft", "certification", "other"] = "skill"
    synonyms: list[str] = Field(default_factory=list)


class JobAnalysis(BaseModel):
    title: str | None = None
    company: str | None = None
    seniority: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[Keyword] = Field(default_factory=list)
    summary: str | None = None


# --------------------------------------------------------------------------
# Plan (stage: plan) and rewrite (stage: rewrite).
# --------------------------------------------------------------------------


class TermEvidence(BaseModel):
    """The planner's claim that words in the resume show the work a job term names.
    `resume_quote` must occur verbatim in the resume; code checks that, and the claim
    verifier checks that the quote really means the term."""

    job_term: str
    resume_quote: str


class BlockPlan(BaseModel):
    block_id: str
    action: Literal["rewrite", "keep"] = "rewrite"
    # Only JD keywords the resume already evidences. The planner must not ask the
    # writer to introduce anything the candidate has not done.
    target_keywords: list[str] = Field(default_factory=list)
    evidence: str = ""
    instruction: str = ""
    # Job terms the block may use although it never spells them, each backed by a quote.
    term_evidence: list[TermEvidence] = Field(default_factory=list)


class TailoringPlan(BaseModel):
    positioning: str = ""
    # The planner's own rewrite of the summary. It sees the whole resume and the job, so
    # it writes this one block itself; the text goes through the same gates as any edit.
    summary_text: str = ""
    block_plans: list[BlockPlan] = Field(default_factory=list)
    # JD keywords with no evidence in the resume. Surfaced to the user, never inserted.
    gaps: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0, le=1)


class BlockRewrite(BaseModel):
    block_id: str
    new_text: str
    reason: str = ""
    keywords_used: list[str] = Field(default_factory=list)


class RewriteBatch(BaseModel):
    rewrites: list[BlockRewrite] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Validation and scoring.
# --------------------------------------------------------------------------


class Violation(BaseModel):
    rule_key: str
    block_id: str | None = None
    detail: str
    severity: Literal["block", "warn"] = "block"


class ValidationOutcome(BaseModel):
    rule_key: str
    rule_version: str
    passed: bool
    score: float | None = None
    threshold: float | None = None
    details: dict = Field(default_factory=dict)


class Scores(BaseModel):
    ats: float
    job_alignment: float
    keyword_relevance: float
    formatting: float


class HiringManagerFeedback(BaseModel):
    """Always labelled as an AI simulation in the UI. No outcome guarantees."""

    overall: float = Field(ge=0, le=100)
    technical_alignment: float = Field(ge=0, le=100)
    leadership: float = Field(ge=0, le=100)
    domain_alignment: float = Field(ge=0, le=100)
    communication: float = Field(ge=0, le=100)
    interview_likelihood: Literal["low", "moderate", "high"]
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggested_improvements: list[str] = Field(default_factory=list)
    competitive_positioning: str = ""


# --------------------------------------------------------------------------
# Pipeline result handed to persistence.
# --------------------------------------------------------------------------


class Change(BaseModel):
    """One row of resume_changes."""

    block_path: str
    prior_text: str
    proposed_text: str
    reason: str
    prioritized_keywords: list[str] = Field(default_factory=list)


class TailoringResult(BaseModel):
    structure: ResumeStructure
    job: JobAnalysis
    plan: TailoringPlan
    changes: list[Change]
    # Edits that passed every gate, by block id. Rejected edits fall back to
    # the original text (partial recovery).
    edits: dict[str, str]
    validations: list[ValidationOutcome]
    scores_before: Scores
    scores_after: Scores
    feedback: HiringManagerFeedback | None = None
    total_cost_usd: float = 0.0


class ClaimVerdict(BaseModel):
    block_id: str
    supported: bool
    unsupported_claims: list[str] = Field(default_factory=list)


class ClaimCheck(BaseModel):
    """Output of the verify_claims stage: is each rewrite entailed by the original?"""

    results: list[ClaimVerdict] = Field(default_factory=list)
