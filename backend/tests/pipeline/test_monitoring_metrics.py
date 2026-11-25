"""Prometheus metrics: helpers, the AI-call sink, TeeSink and per-generation metrics."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from roletailor.ai.cache import MemoryCache
from roletailor.ai.gateway import build_gateway
from roletailor.ai.monitoring import PrometheusSink, TeeSink, base_stage, error_label, route_of
from roletailor.ai.providers.fake import FakeProvider
from roletailor.ai.telemetry import CallRecord, MemorySink
from roletailor.config import Settings
from roletailor.documents import read_docx
from roletailor.pipeline.orchestrator import BLOCKING_RULES, TailoringPrefs, tailor
from roletailor.worker import metrics as wm
from tests.fixtures.make_fixtures import make_classic_resume
from tests.pipeline.test_orchestrator import JD


def val(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def rec(**kw) -> CallRecord:
    base = dict(stage="it1:plan", attempt=1, provider="prov", model_name="mod", model_revision="r",
                capability_tier="low", prompt_key="k", prompt_version=1, prompt_text="t",
                status="succeeded", routing_reason="primary", latency_ms=1500, input_tokens=10,
                output_tokens=5, estimated_cost_usd=0.01)
    return CallRecord(**{**base, **kw})


@pytest.mark.parametrize("label,expected", [
    ("it1:rewrite:r0b2", "rewrite"), ("it1:plan", "plan"), ("it2:verify_claims:r1", "verify_claims"),
    ("structure_resume", "structure_resume"), ("weird", "other"), ("it1:nope", "other"),
])
def test_base_stage(label, expected):
    assert base_stage(label) == expected


@pytest.mark.parametrize("reason,expected", [
    ("primary tier=low", "primary"), ("failover#1 x", "failover"), ("tier escalated+1", "escalated"),
    ("cache_hit", "cache"), ("failover#1 escalated+1", "escalated"),
])
def test_route_of(reason, expected):
    assert route_of(reason) == expected


def test_error_label():
    assert error_label(None) == "unknown"
    assert error_label("") == "unknown"
    assert error_label("Rate Limit/429!") == "rate_limit_429_"
    assert len(error_label("x" * 100)) == 32


def test_succeeded_call_is_counted():
    lab = dict(stage="plan", provider="prov", model="mod")
    calls = dict(**lab, tier="low", status="succeeded", route="primary")
    before = (val("roletailor_ai_calls_total", **calls), val("roletailor_ai_call_seconds_count", **lab),
              val("roletailor_ai_cost_usd_total", **lab),
              val("roletailor_ai_tokens_total", stage="plan", provider="prov", kind="input"))
    PrometheusSink().record(rec())
    assert val("roletailor_ai_calls_total", **calls) == before[0] + 1
    assert val("roletailor_ai_call_seconds_count", **lab) == before[1] + 1
    assert val("roletailor_ai_cost_usd_total", **lab) == pytest.approx(before[2] + 0.01)
    assert val("roletailor_ai_tokens_total", stage="plan", provider="prov", kind="input") == before[3] + 10


def test_cached_call_has_no_latency_or_cost():
    lab = dict(stage="analyze_job", provider="prov", model="mod")
    calls = dict(**lab, tier="low", status="cached", route="cache")
    b = (val("roletailor_ai_calls_total", **calls), val("roletailor_ai_call_seconds_count", **lab),
         val("roletailor_ai_cost_usd_total", **lab))
    PrometheusSink().record(rec(stage="it1:analyze_job", status="cached", routing_reason="cache_hit",
                                latency_ms=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0))
    assert val("roletailor_ai_calls_total", **calls) == b[0] + 1
    assert val("roletailor_ai_call_seconds_count", **lab) == b[1]
    assert val("roletailor_ai_cost_usd_total", **lab) == b[2]


def test_failed_call_counts_error():
    lab = dict(stage="rewrite", provider="prov", error_code="rate_limit")
    before = val("roletailor_ai_errors_total", **lab)
    PrometheusSink().record(rec(stage="it1:rewrite:r0b1", status="failed", error_code="RATE_LIMIT",
                                estimated_cost_usd=0.0))
    assert val("roletailor_ai_errors_total", **lab) == before + 1


def test_prometheus_sink_swallows_errors():
    PrometheusSink().record(None)  # type: ignore[arg-type]


class Boom:
    def record(self, rec: CallRecord) -> None:
        raise RuntimeError("db down")


def test_tee_forwards_in_order_and_tracks_cost():
    a, b = MemorySink(), MemorySink()
    tee = TeeSink(a, b)
    tee.record(rec(estimated_cost_usd=0.01))
    tee.record(rec(estimated_cost_usd=0.02))
    assert len(a.records) == len(b.records) == 2
    assert tee.total_cost_usd == pytest.approx(0.03)


def test_tee_survives_prometheus_sink_but_propagates_other_sinks(monkeypatch):
    mem = MemorySink()
    monkeypatch.setattr(PrometheusSink, "_emit", staticmethod(lambda r: 1 / 0))
    TeeSink(PrometheusSink(), mem).record(rec())
    assert len(mem.records) == 1
    tee = TeeSink(Boom(), mem)
    with pytest.raises(RuntimeError):
        tee.record(rec(estimated_cost_usd=0.5))
    assert tee.total_cost_usd == pytest.approx(0.5)  # spend counted even when a sink fails


def test_observe_generation_matches_validations():
    doc = read_docx(make_classic_resume())
    provider = FakeProvider()
    gw = build_gateway(MemorySink(), settings=Settings(llm_mode="fake"), cache=MemoryCache(),
                       providers={"anthropic": provider, "deepseek": provider})
    result = tailor(document=doc, job_text=JD, prefs=TailoringPrefs(), gateway=gw)
    by_rule = {o.rule_key: o for o in result.validations}
    planned = by_rule["pipeline.coverage"].details["planned_blocks"]
    expected_flagged = {r: round((1 - by_rule[r].score / 100) * planned) for r in BLOCKING_RULES}
    expected_reverted = {r: len(by_rule[r].details["reverted_to_original"]) for r in BLOCKING_RULES}

    def snap():
        return (val("roletailor_validation_planned_blocks_total"),
                {r: val("roletailor_validation_flagged_blocks_total", rule=r) for r in BLOCKING_RULES},
                {r: val("roletailor_validation_reverted_blocks_total", rule=r) for r in BLOCKING_RULES},
                val("roletailor_generation_cost_usd_count"),
                val("roletailor_generation_checks_total", check="degraded_job", result="pass"))

    p0, f0, r0, c0, d0 = snap()
    wm.observe_generation(result)
    p1, f1, r1, c1, d1 = snap()
    assert p1 - p0 == planned > 0
    assert {r: f1[r] - f0[r] for r in f0} == expected_flagged
    assert {r: r1[r] - r0[r] for r in r0} == expected_reverted
    assert c1 - c0 == 1
    assert d1 - d0 == 1


def test_failed_cost_counter():
    before = val("roletailor_generation_failed_cost_usd_total")
    wm.add_failed_cost(0.0)
    wm.add_failed_cost(0.03)
    assert val("roletailor_generation_failed_cost_usd_total") == pytest.approx(before + 0.03)


def test_fabrication_blocks_count_once_across_rules():
    """A block that trips two fabrication gates is one attempted fabrication, not two."""
    from roletailor.pipeline.orchestrator import _rule_outcomes
    from roletailor.pipeline.validation.rules import Violation

    log = {
        "facts.numbers": [Violation(rule_key="facts.numbers", block_id="b1", detail="x"),
                          Violation(rule_key="facts.numbers", block_id="b2", detail="x")],
        "facts.keywords": [Violation(rule_key="facts.keywords", block_id="b1", detail="x")],
        "layout.length": [Violation(rule_key="layout.length", block_id="b3", detail="x")],
    }
    by_rule = {o.rule_key: o for o in _rule_outcomes(log, ["b2"], 10)}
    fabrication = by_rule["pipeline.fabrication"]
    assert fabrication.details == {"flagged_blocks": 2, "planned_blocks": 10, "reverted_blocks": 1}
    assert fabrication.score == 80.0
