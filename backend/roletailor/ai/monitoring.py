"""Prometheus metrics for AI calls (see docs/monitoring-contract.md).

`PrometheusSink` turns each `CallRecord` into counters and a latency histogram.
`TeeSink` fans a record out to several sinks and keeps a running cost total, so a run
that raises still knows what it spent. Only the Prometheus sink is protected: metric
emission never breaks a generation, but an exception from any other sink (for example
the DB sink) propagates to the caller.
"""

from __future__ import annotations

import logging
import re
import threading

from prometheus_client import Counter, Histogram

from roletailor.ai.telemetry import CallRecord, MetricsSink

log = logging.getLogger(__name__)

STAGES = frozenset({"structure_resume", "analyze_job", "plan", "summary", "rewrite", "verify_claims", "feedback"})
_ITERATION = re.compile(r"^it\d+$")

AI_CALLS = Counter(
    "roletailor_ai_calls_total", "AI calls by outcome",
    ["stage", "provider", "model", "tier", "status", "route"],
)
AI_CALL_SECONDS = Histogram(
    "roletailor_ai_call_seconds", "AI call latency (non-cached calls)", ["stage", "provider", "model"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 45, 60, 90),
)
AI_COST_USD = Counter(
    "roletailor_ai_cost_usd_total", "Estimated AI spend in USD", ["stage", "provider", "model"]
)
AI_TOKENS = Counter(
    "roletailor_ai_tokens_total", "AI tokens by kind", ["stage", "provider", "kind"]
)
AI_ERRORS = Counter(
    "roletailor_ai_errors_total", "AI call errors by code", ["stage", "provider", "error_code"]
)


def base_stage(label: str) -> str:
    """`it1:rewrite:r0b2` -> `rewrite`; unknown names become `other`."""
    parts = label.split(":")
    name = parts[1] if len(parts) > 1 and _ITERATION.match(parts[0]) else parts[0]
    return name if name in STAGES else "other"


def route_of(routing_reason: str) -> str:
    """Classify a routing reason as escalated, failover, cache or primary."""
    if "escalated+" in routing_reason:
        return "escalated"
    if "failover#" in routing_reason:
        return "failover"
    return "cache" if routing_reason == "cache_hit" else "primary"


def error_label(code: str | None) -> str:
    """Bounded, lower-case label value for an error code."""
    if not code:
        return "unknown"
    return re.sub(r"[^a-z0-9_]", "_", code.lower())[:32] or "unknown"


class PrometheusSink:
    """Emits the per-call metrics. Never raises."""

    def record(self, rec: CallRecord) -> None:
        try:
            self._emit(rec)
        except Exception:  # noqa: BLE001 - metrics must never break a generation
            log.debug("prometheus emission failed", exc_info=True)

    @staticmethod
    def _emit(rec: CallRecord) -> None:
        stage = base_stage(rec.stage)
        AI_CALLS.labels(stage, rec.provider, rec.model_name, rec.capability_tier, rec.status,
                        route_of(rec.routing_reason)).inc()
        if rec.status != "cached":
            AI_CALL_SECONDS.labels(stage, rec.provider, rec.model_name).observe(rec.latency_ms / 1000)
        if rec.estimated_cost_usd > 0:
            AI_COST_USD.labels(stage, rec.provider, rec.model_name).inc(rec.estimated_cost_usd)
        for kind, n in (("input", rec.input_tokens), ("output", rec.output_tokens),
                        ("cache_read", rec.cache_read_tokens)):
            if n > 0:
                AI_TOKENS.labels(stage, rec.provider, kind).inc(n)
        if rec.status in ("failed", "timed_out") or rec.error_code:
            AI_ERRORS.labels(stage, rec.provider, error_label(rec.error_code)).inc()


class TeeSink:
    """Forwards each record to every sink in order and tracks the running cost.

    The cost is added before forwarding, so it is counted even if a sink raises. A sink
    that raises (other than `PrometheusSink`, which swallows its own errors) propagates.
    """

    def __init__(self, *sinks: MetricsSink):
        self.sinks = sinks
        self._lock = threading.Lock()
        self._cost = 0.0

    @property
    def total_cost_usd(self) -> float:
        with self._lock:
            return self._cost

    def record(self, rec: CallRecord) -> None:
        with self._lock:
            self._cost += rec.estimated_cost_usd
        for sink in self.sinks:
            sink.record(rec)
