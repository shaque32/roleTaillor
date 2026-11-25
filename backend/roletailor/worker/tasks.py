"""Celery tasks."""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from roletailor.config import get_settings
from roletailor.logging_setup import correlation_id
from roletailor.services import retention, tailoring_runner
from roletailor.worker.celery_app import celery_app
from roletailor.worker.metrics import WORKFLOW_RUN_SECONDS, WORKFLOW_RUNS

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


PURGE_LOCK_KEY = "rt:lock:purge-deleted-resumes"
PURGE_LOCK_SECONDS = 30 * 60


@celery_app.task(name="roletailor.worker.tasks.purge_deleted_resumes")
def purge_deleted_resumes() -> dict[str, int]:
    """Nightly: erase resumes deleted more than `resume_retention_days` ago. Safe to run
    at any time and to repeat; a run that fails part-way is finished by the next one."""
    import redis

    token = correlation_id.set(f"purge-{uuid4().hex[:12]}")
    client = redis.Redis.from_url(get_settings().redis_url)
    try:
        if not client.set(PURGE_LOCK_KEY, "1", nx=True, ex=PURGE_LOCK_SECONDS):
            log.info("retention purge already running, skipping")
            return {"purged": 0, "skipped": 0, "failed": 0, "objects_deleted": 0,
                    "objects_pending": 0}
        try:
            summary = retention.purge_due()
        finally:
            client.delete(PURGE_LOCK_KEY)
        return {"purged": summary.purged, "skipped": summary.skipped, "failed": summary.failed,
                "objects_deleted": summary.objects_deleted,
                "objects_pending": summary.objects_pending}
    finally:
        client.close()
        correlation_id.reset(token)
