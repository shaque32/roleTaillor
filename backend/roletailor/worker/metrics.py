"""Worker-side Prometheus metrics.

With the prefork pool, set PROMETHEUS_MULTIPROC_DIR so child processes share their
samples; the endpoint then aggregates them with MultiProcessCollector."""

from __future__ import annotations

import os

from prometheus_client import CollectorRegistry, Counter, Histogram, start_http_server
from prometheus_client.multiprocess import MultiProcessCollector

from roletailor.domain.models import TailoringResult
from roletailor.pipeline.orchestrator import BLOCKING_RULES

WORKFLOW_RUNS = Counter(
    "roletailor_workflow_runs_total", "Tailoring runs by outcome", ["outcome"]
)
WORKFLOW_RUN_SECONDS = Histogram(
    "roletailor_workflow_run_seconds", "Tailoring run duration from task start, excluding queue wait",
    buckets=(5, 15, 30, 60, 120, 300, 600),
)
GENERATION_COST = Histogram(
    "roletailor_generation_cost_usd", "AI cost of completed generations",
    buckets=(0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.15, 0.25, 0.5, 1),
)
GENERATION_FAILED_COST = Counter(
    "roletailor_generation_failed_cost_usd_total", "AI spend of failed, retried or discarded runs"
)
PLANNED_BLOCKS = Counter("roletailor_validation_planned_blocks_total", "Blocks planned for rewriting")
FLAGGED_BLOCKS = Counter(
    "roletailor_validation_flagged_blocks_total", "Blocks flagged by a blocking rule", ["rule"]
)
REVERTED_BLOCKS = Counter(
    "roletailor_validation_reverted_blocks_total", "Blocks reverted to original by a rule", ["rule"]
)
FABRICATION_BLOCKS = Counter(
    "roletailor_validation_fabrication_blocks_total",
    "Distinct blocks flagged by any fabrication rule (a block counts once)",
)
GENERATION_CHECKS = Counter(
    "roletailor_generation_checks_total", "Per-generation checks by result", ["check", "result"]
)

# Create the label children up front so the first increment is visible to rate()/increase().
for _rule in BLOCKING_RULES:
    FLAGGED_BLOCKS.labels(_rule)
    REVERTED_BLOCKS.labels(_rule)
for _check, _results in (("page_limit", ("pass", "fail", "skipped")), ("degraded_structure", ("pass", "fail")),
                         ("degraded_job", ("pass", "fail")), ("degraded_any", ("pass", "fail")),
                         ("document_authenticity", ("pass", "fail"))):
    for _result in _results:
        GENERATION_CHECKS.labels(_check, _result)
for _outcome in ("completed", "failed", "retried", "skipped", "discarded"):
    WORKFLOW_RUNS.labels(_outcome)


def add_failed_cost(usd: float) -> None:
    """Count AI spend of a run that failed, was retried or was discarded."""
    if usd > 0:
        GENERATION_FAILED_COST.inc(usd)


def observe_generation(result: TailoringResult) -> None:
    """Record cost, validation and check metrics of a completed generation."""
    by_rule = {o.rule_key: o for o in result.validations}
    GENERATION_COST.observe(result.total_cost_usd)
    coverage = by_rule.get("pipeline.coverage")
    planned = int(coverage.details.get("planned_blocks", 0)) if coverage else 0
    PLANNED_BLOCKS.inc(planned)
    for rule in BLOCKING_RULES:
        outcome = by_rule.get(rule)
        if outcome is None:
            continue
        if planned and outcome.score is not None:
            FLAGGED_BLOCKS.labels(rule).inc(round((1 - outcome.score / 100) * planned))
        REVERTED_BLOCKS.labels(rule).inc(len(outcome.details.get("reverted_to_original", [])))

    fabrication = by_rule.get("pipeline.fabrication")
    if fabrication is not None:
        FABRICATION_BLOCKS.inc(int(fabrication.details.get("flagged_blocks", 0)))

    page = by_rule.get("layout.page_limit")
    if page is not None:
        skipped = "skipped" in page.details
        GENERATION_CHECKS.labels("page_limit", "skipped" if skipped else "pass" if page.passed else "fail").inc()
    degraded = by_rule.get("pipeline.degraded")
    any_degraded = False
    for check, key in (("degraded_structure", "structure_heuristic"), ("degraded_job", "job_heuristic")):
        flagged = bool(degraded and degraded.details.get(key))
        any_degraded = any_degraded or flagged
        GENERATION_CHECKS.labels(check, "fail" if flagged else "pass").inc()
    # One count per generation, so a run with both fallbacks is not counted twice.
    GENERATION_CHECKS.labels("degraded_any", "fail" if any_degraded else "pass").inc()
    doc = by_rule.get("authenticity.document")
    if doc is not None and doc.score is not None and doc.threshold is not None:
        GENERATION_CHECKS.labels("document_authenticity", "fail" if doc.score < doc.threshold else "pass").inc()


def start_metrics_server(port: int) -> None:
    if port <= 0:
        return
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        MultiProcessCollector(registry)
        start_http_server(port, registry=registry)
    else:
        start_http_server(port)
