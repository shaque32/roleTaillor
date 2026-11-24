"""Worker-side Prometheus metrics.

With the prefork pool, set PROMETHEUS_MULTIPROC_DIR so child processes share their
samples; the endpoint then aggregates them with MultiProcessCollector."""

from __future__ import annotations

import os

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server
from prometheus_client.multiprocess import MultiProcessCollector

WORKFLOW_RUNS = Counter(
    "roletailor_workflow_runs_total", "Tailoring runs by outcome", ["outcome"]
)
WORKFLOW_RUN_SECONDS = Histogram(
    "roletailor_workflow_run_seconds", "Tailoring run duration", buckets=(5, 15, 30, 60, 120, 300, 600)
)


def start_metrics_server(port: int) -> None:
    if port <= 0:
        return
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        MultiProcessCollector(registry)
        start_http_server(port, registry=registry)
    else:
        start_http_server(port)
