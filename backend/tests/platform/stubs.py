"""Deterministic stand-ins for the AI pipeline, for tests that exercise persistence."""

from __future__ import annotations

from dataclasses import dataclass

from roletailor.ai.telemetry import CallRecord
from roletailor.domain.models import (
    Change,
    HiringManagerFeedback,
    JobAnalysis,
    Keyword,
    ResumeStructure,
    Scores,
    TailoringPlan,
    TailoringResult,
    ValidationOutcome,
)


@dataclass
class StubGateway:
    sink: object
    customer_tier: str = "free"


def stub_build_gateway(sink, **kwargs) -> StubGateway:
    return StubGateway(sink=sink, customer_tier=kwargs.get("customer_tier", "free"))


def _record(gateway: StubGateway, stage: str) -> None:
    gateway.sink.record(CallRecord(
        stage=stage, attempt=1, provider="fake", model_name="fake-model", model_revision="r1",
        capability_tier="low", prompt_key="plan", prompt_version=1, prompt_text="Plan the edits.",
        status="succeeded", routing_reason="default", latency_ms=12, input_tokens=100,
        output_tokens=50, estimated_cost_usd=0.0001,
    ))


def stub_tailor(*, document, job_text, prefs, gateway, source_docx=None, source_pdf=None, cached_structure=None,
                cached_job=None, iteration=1, focus_block_ids=None) -> TailoringResult:
    stage = f"it{iteration}:plan"
    _record(gateway, stage)
    targets = [b for b in document.blocks if b.text.strip() and b.editable and not b.is_heading]
    if focus_block_ids:
        targets = [b for b in targets if b.id in focus_block_ids]
    targets = targets[-2:]
    edits = {b.id: f"{b.text} (Kafka, it{iteration})" for b in targets}
    return TailoringResult(
        structure=cached_structure or ResumeStructure(),
        job=cached_job or JobAnalysis(title="Senior Data Engineer", company="Contoso",
                                      keywords=[Keyword(term="Kafka", importance="must")]),
        plan=TailoringPlan(positioning="Streaming data engineer", gaps=["Terraform"]),
        changes=[Change(block_path=b.id, prior_text=b.text, proposed_text=edits[b.id], reason="Mirror the JD",
                        prioritized_keywords=["Kafka"]) for b in targets],
        edits=edits,
        validations=[
            ValidationOutcome(rule_key="facts.terms", rule_version="1", passed=True, score=100, threshold=90,
                              details={"stage": stage}),
            ValidationOutcome(rule_key="layout.length", rule_version="1", passed=True),
        ],
        scores_before=Scores(ats=55, job_alignment=50, keyword_relevance=45, formatting=90),
        scores_after=Scores(ats=78, job_alignment=74, keyword_relevance=70, formatting=90),
        feedback=HiringManagerFeedback(
            overall=72, technical_alignment=80, leadership=60, domain_alignment=70, communication=75,
            interview_likelihood="moderate", strengths=["Streaming"], weaknesses=["No Terraform"],
        ),
        total_cost_usd=0.0001,
    )
