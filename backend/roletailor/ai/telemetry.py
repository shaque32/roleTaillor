"""Per-call AI telemetry. One `CallRecord` becomes one row in ai_metrics.

The pipeline is persistence-agnostic: it reports through a `MetricsSink`. The worker
supplies a sink that writes ai_metrics rows (and upserts ai_model_versions /
prompt_versions); tests and evals use `MemorySink`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol


@dataclass
class CallRecord:
    stage: str  # unique per workflow iteration, e.g. "it1:rewrite:b2"
    attempt: int
    provider: str
    model_name: str
    model_revision: str
    capability_tier: str  # low | medium | high
    prompt_key: str
    prompt_version: int
    prompt_text: str  # template text for prompt_versions.template_text
    status: str  # succeeded | failed | timed_out | cached
    routing_reason: str
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    estimated_cost_usd: float = 0.0
    error_code: str | None = None
    trace_id: str | None = None
    # When the call finished (timezone-aware UTC), captured by the Gateway before response
    # validation or any sink delay. Persisted as ai_metrics.created_at.
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MetricsSink(Protocol):
    def record(self, rec: CallRecord) -> None: ...


@dataclass
class MemorySink:
    records: list[CallRecord] = field(default_factory=list)

    def record(self, rec: CallRecord) -> None:
        self.records.append(rec)

    @property
    def total_cost(self) -> float:
        return round(sum(r.estimated_cost_usd for r in self.records), 8)

    def by_stage(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in self.records:
            key = r.stage.split(":", 2)[1] if ":" in r.stage else r.stage
            out[key] = out.get(key, 0.0) + r.estimated_cost_usd
        return out
