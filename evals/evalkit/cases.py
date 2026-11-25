"""Eval case schema and loader.

One YAML file per case in evals/cases/. A case is a synthetic resume (rendered to a real
DOCX so the documents engine is exercised), a job description, and the checks that do
not depend on the pipeline's own validators. See evals/README.md for authoring rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
CASES_DIR = ROOT / "evals" / "cases"

Family = Literal[
    "data_ai", "software", "product", "design", "marketing", "sales", "finance", "healthcare",
    "education", "operations", "hr", "legal", "customer_support", "engineering_other", "executive",
]
Seniority = Literal["intern", "junior", "mid", "senior", "lead", "executive"]
Scenario = Literal[
    "strong_match",        # resume already fits; expect terminology alignment, no invention
    "partial_match",       # some requirements evidenced, some real gaps
    "poor_match",          # wrong field; the right answer is few or no edits and honest gaps
    "career_change",       # transferable skills only
    "seniority_stretch",   # JD asks for more years, scope, or people management than shown
    "missing_credential",  # JD requires a licence, degree, or certification the resume lacks
    "keyword_bait",        # JD is a long keyword list that invites stuffing
    "prompt_injection",    # JD or resume text contains instructions aimed at the model
    "no_metrics",          # resume has no numbers; any number in the output is invented
    "metric_heavy",        # many numbers that must survive unchanged
    "sparse_resume",       # new graduate or one short role
    "long_resume",         # close to the page limit; length discipline matters
    "noisy_jd",            # boilerplate, benefits, legal text around few real requirements
    "vague_jd",            # short or generic JD with little to target
    "layout",              # table layout, missing summary, unusual section names
    "unicode",             # non-ASCII names, punctuation, and symbols
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Role(_Strict):
    company: str
    title: str
    dates: str
    bullets: list[str] = Field(min_length=1)


class SkillLine(_Strict):
    label: str  # e.g. "Languages:"
    value: str  # e.g. "Python, SQL"


class Education(_Strict):
    school: str
    degree: str
    year: str | None = None


class ResumeSpec(_Strict):
    layout: Literal["classic", "table"] = "classic"
    name: str
    contact: str  # one line: "City, ST | name@example.com | (555) 555-0100"
    summary: str | None = None
    experience: list[Role] = Field(min_length=1)
    skills: list[SkillLine] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    # Section titles can be overridden to exercise heading detection.
    headings: dict[str, str] = Field(default_factory=dict)

    def lines(self) -> list[str]:
        """Every text line of the resume, for checks that need the full source text."""
        out = [self.name, self.contact]
        if self.summary:
            out.append(self.summary)
        for r in self.experience:
            out += [r.company, r.title, r.dates, *r.bullets]
        out += [f"{s.label} {s.value}" for s in self.skills]
        for e in self.education:
            out += [e.school, e.degree, e.year or ""]
        return [*out, *self.certifications]

    def text(self) -> str:
        return "\n".join(x for x in self.lines() if x)


class Expect(_Strict):
    # Offline and live: fewer accepted changes than this fails the case.
    min_changes: int = 0
    # Live only (the offline provider only swaps synonyms, so it cannot meet these).
    live_min_changes: int | None = None
    live_max_changes: int | None = None  # poor matches should not be rewritten wholesale
    # Terms the plan must report as gaps in live runs (a subset of canaries).
    live_expected_gaps: list[str] = Field(default_factory=list)


class EvalCase(_Strict):
    name: str
    family: Family
    seniority: Seniority
    scenario: Scenario
    # A ResumeSpec, or "classic" / "table" for the two original test fixtures.
    resume: ResumeSpec | Literal["classic", "table"]
    job: str
    # Terms the job asks for that the resume gives no evidence of. If one appears in
    # any edited block, the case fails as a fabrication.
    canaries: list[str] = Field(default_factory=list)
    page_limit: int = 2
    expect: Expect = Field(default_factory=Expect)
    notes: str | None = None

    def resume_bytes(self) -> bytes:
        from evalkit.resume_builder import build_resume, fixture_resume

        return fixture_resume(self.resume) if isinstance(self.resume, str) else build_resume(self.resume)


def load_cases(directory: Path = CASES_DIR, *, names: list[str] | None = None,
               scenarios: list[str] | None = None, families: list[str] | None = None) -> list[EvalCase]:
    cases = [EvalCase.model_validate(yaml.safe_load(p.read_text())) for p in sorted(directory.glob("*.yaml"))]
    seen: set[str] = set()
    for c in cases:
        if c.name in seen:
            raise ValueError(f"duplicate case name: {c.name}")
        seen.add(c.name)
    if names:
        cases = [c for c in cases if c.name in names]
    if scenarios:
        cases = [c for c in cases if c.scenario in scenarios]
    if families:
        cases = [c for c in cases if c.family in families]
    return cases
