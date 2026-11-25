"""Celery tasks."""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from roletailor.logging_setup import correlation_id
from roletailor.services import resume_ocr, tailoring_runner
from roletailor.worker.celery_app import celery_app
from roletailor.worker.metrics import OCR_JOB_SECONDS, OCR_JOBS, WORKFLOW_RUN_SECONDS, WORKFLOW_RUNS

log = logging.getLogger(__name__)
MAX_RETRIES = 2


def _backoff_seconds(retries: int) -> int:
    return 15 * 2**retries  # 15s, 30s


@celery_app.task(bind=True, name="roletailor.worker.tasks.run_tailoring", max_retries=MAX_RETRIES)
def run_tailoring(self, org_id: str, workflow_id: str, iteration: int,
                  focus_block_ids: list[str] | None = None,
                  correlation: str | None = None) -> str:
    token = correlation_id.set(correlation or f"task-{uuid4().hex[:12]}")
    started = time.monotonic()
    try:
        try:
            outcome = tailoring_runner.run(org_id, workflow_id, iteration, focus_block_ids)
        except Exception as exc:
            if tailoring_runner.is_transient(exc) and self.request.retries < MAX_RETRIES:
                log.warning("transient tailoring failure, retrying",
                            extra={"workflow_id": workflow_id, "error": repr(exc)})
                tailoring_runner.mark_retrying(org_id, workflow_id, self.request.retries + 1)
                WORKFLOW_RUNS.labels("retried").inc()
                raise self.retry(exc=exc, countdown=_backoff_seconds(self.request.retries)) from exc
            log.exception("tailoring failed", extra={"workflow_id": workflow_id})
            tailoring_runner.mark_failed(org_id, workflow_id, iteration, exc)
            outcome = "failed"
        WORKFLOW_RUNS.labels(outcome).inc()
        WORKFLOW_RUN_SECONDS.observe(time.monotonic() - started)
        log.info("tailoring run finished", extra={"workflow_id": workflow_id, "outcome": outcome})
        return outcome
    finally:
        correlation_id.reset(token)


@celery_app.task(bind=True, name="roletailor.worker.tasks.ocr_resume", max_retries=MAX_RETRIES)
def ocr_resume(self, org_id: str, resume_id: str, correlation: str | None = None) -> str:
    """Read a scanned resume with OCR (see services/resume_ocr). Idempotent under redelivery."""
    token = correlation_id.set(correlation or f"task-{uuid4().hex[:12]}")
    started = time.monotonic()
    try:
        try:
            outcome = resume_ocr.run(org_id, resume_id)
        except Exception as exc:
            if resume_ocr.is_transient(exc) and self.request.retries < MAX_RETRIES:
                log.warning("transient ocr failure, retrying",
                            extra={"resume_id": resume_id, "error": repr(exc)})
                OCR_JOBS.labels("retried").inc()
                raise self.retry(exc=exc, countdown=_backoff_seconds(self.request.retries)) from exc
            log.exception("ocr failed", extra={"resume_id": resume_id})
            resume_ocr.mark_failed(org_id, resume_id, resume_ocr.FAILED)
            outcome = resume_ocr.FAILED
        OCR_JOBS.labels(outcome).inc()
        OCR_JOB_SECONDS.observe(time.monotonic() - started)
        log.info("ocr finished", extra={"resume_id": resume_id, "outcome": outcome})
        return outcome
    finally:
        correlation_id.reset(token)
