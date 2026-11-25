"""Celery application. Run with: celery -A roletailor.worker.celery_app worker"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging, worker_ready

from roletailor.config import get_settings
from roletailor.logging_setup import configure_logging

settings = get_settings()

celery_app = Celery("roletailor", broker=settings.redis_url, include=["roletailor.worker.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,  # a crashed worker's task is redelivered; the run claims idempotently
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # generations are long; do not hoard them
    broker_connection_retry_on_startup=True,
    task_always_eager=settings.celery_task_always_eager,
    timezone="UTC",
    # Runs only where the worker is started with -B (see deploy/fly/api.toml). The task
    # takes a lock, so a second scheduler by mistake cannot run the purge twice at once.
    beat_schedule={
        "purge-deleted-resumes": {
            "task": "roletailor.worker.tasks.purge_deleted_resumes",
            "schedule": crontab(hour=settings.retention_purge_hour_utc, minute=17),
        },
    },
)


@setup_logging.connect
def _configure_logging(**_: object) -> None:
    configure_logging(settings.log_level)


@worker_ready.connect
def _start_metrics_server(**_: object) -> None:
    from roletailor.worker.metrics import start_metrics_server

    start_metrics_server(settings.worker_metrics_port)
