"""Tailoring workflows: creation (idempotent, quota-checked), state changes, reads."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import Connection, text

from roletailor import db
from roletailor.config import get_settings
from roletailor.logging_setup import correlation_id
from roletailor.services import audit, billing, resumes, users
from roletailor.services.auth import Principal
from roletailor.services.errors import AppError, invalid_state, not_found
from roletailor.services.sql import fetch_all, fetch_one, jsonb

log = logging.getLogger(__name__)

WORKFLOW_COLUMNS = (
    "id, status, source_resume_version_id AS resume_version_id, job_posting_id, page_limit,"
    " draft_state, paid_usage_accepted_at, created_at, updated_at"
)
FEEDBACK_EXTRA_KEYS = ("scores_before", "gaps", "positioning")


def _get_owned(conn: Connection, principal: Principal, workflow_id: UUID, *, lock=False) -> dict:
    row = fetch_one(
        conn,
        f"SELECT {WORKFLOW_COLUMNS} FROM tailoring_workflows WHERE id = :id AND requested_by = :uid"
        + (" FOR UPDATE" if lock else ""),
        {"id": workflow_id, "uid": principal.user_id},
    )
    if row is None:
        raise not_found("Workflow")
    return row


def _set_status(conn: Connection, workflow_id: UUID, status: str, draft_state: dict | None = None) -> dict:
    row = fetch_one(
        conn,
        "UPDATE tailoring_workflows SET status = :s, updated_at = now(),"
        " draft_state = coalesce(CAST(:state AS jsonb), draft_state)"
        f" WHERE id = :id RETURNING {WORKFLOW_COLUMNS}",
        {"s": status, "id": workflow_id, "state": jsonb(draft_state) if draft_state is not None else None},
    )
    assert row is not None
    return row


def _run_state(iteration: int, focus_block_ids: list[str] | None, instructions: str | None = None) -> dict:
    run: dict = {"iteration": iteration, "focus_block_ids": focus_block_ids}
    if instructions:
        run["instructions"] = instructions
    return {"run": run}


def _enqueue(principal: Principal, workflow_id: UUID, run: dict) -> None:
    """Hand the run to Celery. If the broker is down, park the workflow in draft so an
    idempotent replay (or /resume) can enqueue it again."""
    from roletailor.worker.tasks import run_tailoring

    try:
        run_tailoring.apply_async(
            args=[str(principal.org_id), str(workflow_id), run["iteration"], run["focus_block_ids"]],
            kwargs={"correlation": correlation_id.get()},
        )
    except Exception as exc:  # kombu raises several unrelated types when the broker is down
        log.exception("enqueue failed", extra={"workflow_id": str(workflow_id)})
        with db.tenant_tx(principal.org_id) as conn:
            conn.execute(
                text("UPDATE tailoring_workflows SET status = 'draft' WHERE id = :id AND status = 'queued'"),
                {"id": workflow_id},
            )
        raise AppError(503, "queue_unavailable", "We could not start the generation. Try again.") from exc


def create(
    principal: Principal,
    *,
    resume_version_id: UUID,
    job_posting_id: UUID,
    page_limit: int | None,
    accept_paid_usage: bool,
    idempotency_key: str,
) -> dict:
    pending_run: dict | None = None
    with db.tenant_tx(principal.org_id) as conn:
        existing = fetch_one(
            conn,
            f"SELECT {WORKFLOW_COLUMNS} FROM tailoring_workflows WHERE idempotency_key = :k FOR UPDATE",
            {"k": idempotency_key},
        )
        if existing is not None:
            if (existing["resume_version_id"], existing["job_posting_id"]) != (resume_version_id, job_posting_id):
                raise AppError(409, "idempotency_conflict",
                               "This Idempotency-Key was already used for a different request.")
            workflow = existing
            if existing["status"] == "draft":  # an earlier enqueue failed; try again
                workflow = _set_status(conn, existing["id"], "queued")
                pending_run = workflow["draft_state"].get("run") or _run_state(1, None)["run"]
        else:
            resumes.get_owned_version(conn, principal, resume_version_id)
            if fetch_one(conn, "SELECT 1 FROM job_postings WHERE id = :id", {"id": job_posting_id}) is None:
                raise not_found("Job posting")
            billing.ensure_can_start(conn, paid_usage_accepted=accept_paid_usage)
            if page_limit is None:
                page_limit = users.preferences(conn, principal.user_id)["preferred_page_limit"]
            pending_run = _run_state(1, None)["run"]
            workflow = fetch_one(
                conn,
                "INSERT INTO tailoring_workflows (organization_id, requested_by,"
                " source_resume_version_id, job_posting_id, idempotency_key, status, page_limit,"
                " draft_state, paid_usage_accepted_at)"
                " VALUES (:org, :uid, :rv, :job, :key, 'queued', :pages, CAST(:state AS jsonb),"
                " CASE WHEN :accepted THEN now() END)"
                f" RETURNING {WORKFLOW_COLUMNS}",
                {
                    "org": principal.org_id, "uid": principal.user_id, "rv": resume_version_id,
                    "job": job_posting_id, "key": idempotency_key,
                    "pages": page_limit or get_settings().default_page_limit,
                    "state": jsonb({"run": pending_run}), "accepted": accept_paid_usage,
                },
            )
            assert workflow is not None
            audit.record(
                conn, org_id=principal.org_id, action="workflow.created",
                resource_type="tailoring_workflow", resource_id=workflow["id"],
                actor_user_id=principal.user_id, metadata={"accept_paid_usage": accept_paid_usage},
            )
    if pending_run is None:
        return workflow
    _enqueue(principal, workflow["id"], pending_run)
    return get_workflow(principal, workflow["id"])


def get_workflow(principal: Principal, workflow_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        return _get_owned(conn, principal, workflow_id)


def dashboard(principal: Principal) -> list[dict]:
    with db.tenant_tx(principal.org_id) as conn:
        return fetch_all(
            conn,
            "SELECT w.id, w.status, r.name AS resume_name, j.title AS target_role, j.company,"
            " g.ats_score, g.simulation_score, w.created_at"
            " FROM tailoring_workflows w"
            " JOIN resume_versions v ON v.id = w.source_resume_version_id"
            " JOIN resumes r ON r.id = v.resume_id"
            " JOIN job_postings j ON j.id = w.job_posting_id"
            " LEFT JOIN LATERAL (SELECT ats_score, simulation_score FROM generated_resumes"
            "   WHERE workflow_id = w.id ORDER BY iteration DESC LIMIT 1) g ON true"
            " WHERE w.requested_by = :uid"
            " ORDER BY w.created_at DESC LIMIT 200",
            {"uid": principal.user_id},
        )


GENERATED_COLUMNS = (
    "id, workflow_id, iteration, resume_version_id, ats_score, job_alignment_score,"
    " keyword_relevance_score, formatting_score, simulation_score, simulated_feedback,"
    " approved_at, created_at"
)
CHANGE_COLUMNS = (
    "id, block_path, prior_text, proposed_text, reason, prioritized_keywords, decision, decided_at"
)


def detail(principal: Principal, workflow_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        workflow = _get_owned(conn, principal, workflow_id)
        job = fetch_one(conn, "SELECT title, company FROM job_postings WHERE id = :id",
                        {"id": workflow["job_posting_id"]})
        latest = fetch_one(
            conn,
            f"SELECT {GENERATED_COLUMNS} FROM generated_resumes WHERE workflow_id = :wf"
            " ORDER BY iteration DESC LIMIT 1",
            {"wf": workflow_id},
        )
        changes = fetch_all(
            conn,
            f"SELECT {CHANGE_COLUMNS} FROM resume_changes WHERE generated_resume_id = :g ORDER BY block_path",
            {"g": latest["id"]},
        ) if latest else []
    simulated = (latest or {}).get("simulated_feedback") or {}
    feedback = {k: v for k, v in simulated.items() if k not in FEEDBACK_EXTRA_KEYS}
    return {
        "workflow": {
            **workflow,
            "target_role": job["title"] if job else None,
            "company": job["company"] if job else None,
            "recovery_message": recovery_message(workflow),
        },
        "latest": latest,
        "scores_before": simulated.get("scores_before"),
        "gaps": simulated.get("gaps", []),
        "positioning": simulated.get("positioning"),
        "feedback": feedback if "overall" in feedback else None,
        "changes": changes,
    }


def recovery_message(workflow: dict) -> str | None:
    """User-facing text for a failed or retrying workflow, from draft_state."""
    state = workflow["draft_state"] or {}
    return (state.get("error") or state.get("notice") or {}).get("message")


def request_iteration(principal: Principal, workflow_id: UUID, focus_block_ids: list[str] | None,
                      instructions: str | None) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        workflow = _get_owned(conn, principal, workflow_id, lock=True)
        last = conn.execute(
            text("SELECT max(iteration) FROM generated_resumes WHERE workflow_id = :wf"),
            {"wf": workflow_id},
        ).scalar_one()
        if last is None or workflow["status"] not in ("completed", "failed"):
            raise invalid_state("Iterations need a finished generation.", status=workflow["status"])
        if last >= get_settings().max_iterations_per_workflow:
            raise AppError(409, "iteration_limit", "This tailoring has reached its revision limit. "
                           "Start a new tailoring to keep refining.")
        state = _run_state(last + 1, focus_block_ids or None, instructions)
        workflow = _set_status(conn, workflow_id, "queued", state)
    _enqueue(principal, workflow_id, state["run"])
    return workflow


def pause(principal: Principal, workflow_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        workflow = _get_owned(conn, principal, workflow_id, lock=True)
        if workflow["status"] not in ("draft", "queued"):
            raise invalid_state("Only queued workflows can be paused.", status=workflow["status"])
        return _set_status(conn, workflow_id, "paused")


def resume(principal: Principal, workflow_id: UUID) -> dict:
    """Continue a paused workflow, or retry a failed one, with its pending run."""
    with db.tenant_tx(principal.org_id) as conn:
        workflow = _get_owned(conn, principal, workflow_id, lock=True)
        if workflow["status"] not in ("paused", "failed", "draft"):
            raise invalid_state("Only paused or failed workflows can be resumed.", status=workflow["status"])
        state = {k: v for k, v in workflow["draft_state"].items() if k not in ("error", "notice")}
        state.setdefault("run", _run_state(1, None)["run"])
        workflow = _set_status(conn, workflow_id, "queued", state)
    _enqueue(principal, workflow_id, state["run"])
    return workflow


def cancel(principal: Principal, workflow_id: UUID) -> dict:
    with db.tenant_tx(principal.org_id) as conn:
        workflow = _get_owned(conn, principal, workflow_id, lock=True)
        if workflow["status"] in ("completed", "cancelled"):
            raise invalid_state("This workflow has already finished.", status=workflow["status"])
        workflow = _set_status(conn, workflow_id, "cancelled")
        audit.record(
            conn, org_id=principal.org_id, action="workflow.cancelled",
            resource_type="tailoring_workflow", resource_id=workflow_id, actor_user_id=principal.user_id,
        )
        return workflow
