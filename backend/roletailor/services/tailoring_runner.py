"""Run one tailoring iteration for a workflow and persist everything it produced.

Three short transactions: claim (queued -> running, load inputs), the AI pipeline
outside any transaction, then persist + charge atomically. Persisting re-locks the
workflow and discards the result if it was cancelled meanwhile. Failures never charge.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import Connection, text

from roletailor import db
from roletailor.ai.providers.base import ProviderError
from roletailor.domain.models import JobAnalysis, ResumeStructure, TailoringResult
from roletailor.logging_setup import correlation_id
from roletailor.services import audit, billing, files, rendering, resumes, users
from roletailor.services.errors import AppError
from roletailor.services.metrics_sink import DbMetricsSink
from roletailor.services.sql import fetch_one, jsonb
from roletailor.storage import DOCX_MEDIA_TYPE

log = logging.getLogger(__name__)

SIMULATION_LABEL = "AI simulation. Not a prediction of hiring outcomes."
JOB_SHA_KEY = "_description_sha256"
WORKFLOW_COLUMNS = (
    "id, requested_by, source_resume_version_id, job_posting_id, status, page_limit,"
    " draft_state, paid_usage_accepted_at"
)


def is_transient(exc: BaseException) -> bool:
    """Provider outages and network blips are worth a Celery retry."""
    from roletailor.ai.gateway import AIUnavailable

    if isinstance(exc, ProviderError):
        return exc.transient
    return isinstance(exc, AIUnavailable | httpx.TransportError)


@dataclass(frozen=True)
class RunInputs:
    workflow: dict
    base: rendering.Base
    job: dict
    prefs: dict
    customer_tier: str


def _job_sha(description: str) -> str:
    return hashlib.sha256(description.encode()).hexdigest()


def _base_version(conn: Connection, workflow: dict, iteration: int) -> dict:
    """Iteration 1 tailors the source; later iterations build on the previous output."""
    if iteration > 1:
        previous = fetch_one(
            conn,
            "SELECT resume_version_id FROM generated_resumes WHERE workflow_id = :wf"
            " AND iteration = :it",
            {"wf": workflow["id"], "it": iteration - 1},
        )
        if previous is not None:
            return resumes.get_version(conn, previous["resume_version_id"])
    return resumes.get_version(conn, workflow["source_resume_version_id"])


def _claim(org_id: str, workflow_id: str, iteration: int) -> RunInputs | None:
    with db.tenant_tx(org_id) as conn:
        workflow = fetch_one(
            conn,
            f"UPDATE tailoring_workflows SET status = 'running', updated_at = now()"
            f" WHERE id = :id AND status = 'queued' RETURNING {WORKFLOW_COLUMNS}",
            {"id": workflow_id},
        )
        if workflow is None:
            return None  # paused, cancelled, or a duplicate delivery
        job = fetch_one(
            conn,
            "SELECT id, title, company, description, structured_requirements FROM job_postings"
            " WHERE id = :id",
            {"id": workflow["job_posting_id"]},
        )
        assert job is not None
        tier = "subscription" if billing.quota(conn).subscription else "free"
        return RunInputs(
            workflow=workflow,
            base=rendering.load_base(conn, _base_version(conn, workflow, iteration)),
            job=job,
            prefs=users.preferences(conn, workflow["requested_by"]),
            customer_tier=tier,
        )


def _cached_job(job: dict) -> JobAnalysis | None:
    stored = dict(job["structured_requirements"] or {})
    if stored.pop(JOB_SHA_KEY, None) != _job_sha(job["description"] or ""):
        return None
    return JobAnalysis.model_validate(stored)


def _run_pipeline(inputs: RunInputs, sink: DbMetricsSink, iteration: int,
                  focus_block_ids: list[str] | None) -> TailoringResult:
    from roletailor.ai.gateway import build_gateway
    from roletailor.pipeline.orchestrator import TailoringPrefs, tailor

    prefs = inputs.prefs
    gateway = build_gateway(sink, customer_tier=inputs.customer_tier, trace_id=correlation_id.get())
    structure = inputs.base.structure
    return tailor(
        document=inputs.base.document,
        job_text=inputs.job["description"] or "",
        prefs=TailoringPrefs(
            page_limit=inputs.workflow["page_limit"],
            tone=prefs["resume_tone"],
            technical_depth=prefs["technical_depth"],
            industry_focus=prefs["industry_focus"],
            ats_preference=prefs["ats_preference"],
            customer_tier=inputs.customer_tier,
        ),
        gateway=gateway,
        source_docx=inputs.base.docx,
        cached_structure=ResumeStructure.model_validate(structure) if structure else None,
        cached_job=_cached_job(inputs.job),
        iteration=iteration,
        focus_block_ids=focus_block_ids,
    )


def simulated_feedback(result: TailoringResult) -> dict[str, Any]:
    feedback = result.feedback.model_dump() if result.feedback else {}
    return {
        **feedback,
        "label": SIMULATION_LABEL,
        "scores_before": result.scores_before.model_dump(),
        "gaps": result.plan.gaps,
        "positioning": result.plan.positioning,
    }


def _cache_analysis(conn: Connection, inputs: RunInputs, result: TailoringResult) -> None:
    if inputs.base.structure is None:
        conn.execute(
            text(
                "UPDATE resume_versions SET content = jsonb_set(content, '{structure}',"
                " CAST(:s AS jsonb)) WHERE id = :id"
            ),
            {"s": jsonb(result.structure.model_dump()), "id": inputs.base.version["id"]},
        )
    job = inputs.job
    conn.execute(
        text(
            "UPDATE job_postings SET structured_requirements = CAST(:req AS jsonb),"
            " title = coalesce(title, :title), company = coalesce(company, :company)"
            " WHERE id = :id"
        ),
        {
            "req": jsonb({**result.job.model_dump(), JOB_SHA_KEY: _job_sha(job["description"] or "")}),
            "title": result.job.title, "company": result.job.company, "id": job["id"],
        },
    )


def _insert_generated(conn: Connection, inputs: RunInputs, result: TailoringResult,
                      iteration: int, version_id: UUID) -> dict:
    after = result.scores_after
    row = fetch_one(
        conn,
        "INSERT INTO generated_resumes (organization_id, workflow_id, iteration, resume_version_id,"
        " ats_score, job_alignment_score, keyword_relevance_score, formatting_score,"
        " simulation_score, simulated_feedback)"
        " VALUES (roletailor.current_organization_id(), :wf, :it, :v, :ats, :align, :kw, :fmt,"
        " :sim, CAST(:fb AS jsonb)) RETURNING id",
        {
            "wf": inputs.workflow["id"], "it": iteration, "v": version_id,
            "ats": after.ats, "align": after.job_alignment, "kw": after.keyword_relevance,
            "fmt": after.formatting,
            "sim": result.feedback.overall if result.feedback else None,
            "fb": jsonb(simulated_feedback(result)),
        },
    )
    assert row is not None
    return row


def _insert_changes_and_validations(conn: Connection, workflow_id: UUID, generated_id: UUID,
                                    result: TailoringResult, metric_ids: dict[str, UUID]) -> None:
    for change in result.changes:
        conn.execute(
            text(
                "INSERT INTO resume_changes (organization_id, generated_resume_id, block_path,"
                " prior_text, proposed_text, reason, prioritized_keywords)"
                " VALUES (roletailor.current_organization_id(), :g, :path, :prior, :proposed,"
                " :reason, :kw)"
            ),
            {"g": generated_id, "path": change.block_path, "prior": change.prior_text,
             "proposed": change.proposed_text, "reason": change.reason,
             "kw": change.prioritized_keywords},
        )
    for outcome in result.validations:
        stage = outcome.details.get("stage") if isinstance(outcome.details, dict) else None
        conn.execute(
            text(
                "INSERT INTO validation_results (organization_id, workflow_id, ai_metric_id,"
                " rule_key, rule_version, passed, score, threshold, details)"
                " VALUES (roletailor.current_organization_id(), :wf, :metric, :key, :ver, :passed,"
                " :score, :threshold, CAST(:details AS jsonb))"
            ),
            {"wf": workflow_id, "metric": metric_ids.get(stage) if stage else None,
             "key": outcome.rule_key, "ver": outcome.rule_version, "passed": outcome.passed,
             "score": outcome.score, "threshold": outcome.threshold,
             "details": jsonb(outcome.details)},
        )


def _persist(org_id: str, inputs: RunInputs, result: TailoringResult, docx: bytes,
             iteration: int, metric_ids: dict[str, UUID]) -> bool:
    workflow_id = inputs.workflow["id"]
    with db.tenant_tx(org_id) as conn:
        current = fetch_one(
            conn, "SELECT status FROM tailoring_workflows WHERE id = :id FOR UPDATE",
            {"id": workflow_id},
        )
        if current is None or current["status"] != "running":
            return False
        _cache_analysis(conn, inputs, result)
        base = inputs.base.version
        stored = files.store(
            conn, org_id, docx, media_type=DOCX_MEDIA_TYPE,
            filename=f"tailored-v{iteration}.docx", category="generated",
        )
        child = resumes.insert_version(
            conn, base["resume_id"],
            content={
                "source_format": inputs.base.document.source_format,
                "blocks": [b.model_dump() for b in rendering.edited_blocks(inputs.base.document,
                                                                            result.edits)],
                "structure": result.structure.model_dump(),
            },
            layout_metadata=base["layout_metadata"], findings=base["extraction_findings"],
            source_file_id=stored["id"], parent_version_id=base["id"],
        )
        generated = _insert_generated(conn, inputs, result, iteration, child["id"])
        _insert_changes_and_validations(conn, workflow_id, generated["id"], result, metric_ids)
        charge = billing.charge_initial_generation(conn, inputs.workflow) if iteration == 1 else None
        conn.execute(
            text(
                "UPDATE tailoring_workflows SET status = 'completed', draft_state = '{}',"
                " updated_at = now() WHERE id = :id"
            ),
            {"id": workflow_id},
        )
        audit.record(
            conn, org_id=org_id, action="workflow.completed", resource_type="tailoring_workflow",
            resource_id=workflow_id, actor_user_id=inputs.workflow["requested_by"],
            metadata={"iteration": iteration, "generated_resume_id": str(generated["id"]),
                      "charge_type": charge.charge_type if charge else None,
                      "cost_usd": result.total_cost_usd},
        )
    return True


def run(org_id: str, workflow_id: str, iteration: int,
        focus_block_ids: list[str] | None = None) -> str:
    """Execute one iteration. Returns the outcome: completed, skipped or discarded.
    Exceptions propagate to the task, which retries or calls `mark_failed`."""
    inputs = _claim(org_id, workflow_id, iteration)
    if inputs is None:
        return "skipped"
    sink = DbMetricsSink(org_id, workflow_id)
    result = _run_pipeline(inputs, sink, iteration, focus_block_ids)
    docx = rendering.render_with_edits(inputs.base, result.edits, result.structure.model_dump())
    if not _persist(org_id, inputs, result, docx, iteration, sink.metric_ids):
        return "discarded"
    return "completed"


def mark_retrying(org_id: str, workflow_id: str, attempt: int) -> None:
    with db.tenant_tx(org_id) as conn:
        conn.execute(
            text(
                "UPDATE tailoring_workflows SET status = 'queued', updated_at = now(),"
                " draft_state = draft_state || CAST(:state AS jsonb) WHERE id = :id AND status = 'running'"
            ),
            {"id": workflow_id, "state": jsonb({"notice": {
                "code": "retrying", "attempt": attempt,
                "message": "Our AI provider is busy. We are retrying automatically.",
            }})},
        )


def _recovery_message(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, AppError):
        return exc.code, exc.message
    if is_transient(exc):
        return "ai_unavailable", (
            "Our AI service is temporarily unavailable. Nothing was charged. "
            "Please try again in a few minutes."
        )
    return "generation_failed", (
        "Something went wrong while tailoring your resume. Nothing was charged. "
        "Try again, or upload a DOCX version of your resume if the problem persists."
    )


def mark_failed(org_id: str, workflow_id: str, iteration: int, exc: BaseException) -> None:
    code, message = _recovery_message(exc)
    with db.tenant_tx(org_id) as conn:
        row = fetch_one(
            conn,
            "UPDATE tailoring_workflows SET status = 'failed', updated_at = now(),"
            " draft_state = draft_state || CAST(:state AS jsonb)"
            " WHERE id = :id AND status IN ('queued', 'running') RETURNING requested_by",
            {"id": workflow_id, "state": jsonb({"error": {
                "code": code, "message": message, "iteration": iteration,
                "retryable": code != "generation_failed",
            }})},
        )
        if row is None:
            return
        audit.record(
            conn, org_id=org_id, action="workflow.failed", resource_type="tailoring_workflow",
            resource_id=workflow_id, actor_user_id=row["requested_by"],
            metadata={"iteration": iteration, "error_type": type(exc).__name__, "code": code},
        )
