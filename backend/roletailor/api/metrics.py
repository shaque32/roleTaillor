"""API Prometheus metrics."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "roletailor_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "roletailor_http_request_seconds", "HTTP request latency", ["method", "route"]
)
WORKFLOW_REQUESTS = Counter(
    "roletailor_workflow_requests_total", "Workflow creation requests by outcome", ["outcome"]
)
