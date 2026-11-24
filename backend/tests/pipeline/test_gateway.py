import pytest
from pydantic import BaseModel

from roletailor.ai.cache import MemoryCache
from roletailor.ai.gateway import AIUnavailable, build_gateway
from roletailor.ai.providers.base import LLMResponse, ProviderError, Usage
from roletailor.ai.router import ModelRouter
from roletailor.ai.telemetry import MemorySink
from roletailor.config import Settings


class Out(BaseModel):
    value: int


class Scripted:
    """Provider that plays back a script of responses/errors per model."""

    def __init__(self, script: dict[str, list]):
        self.script = script
        self.calls: list[str] = []

    def complete(self, spec, req):
        self.calls.append(spec.model)
        item = self.script[spec.model].pop(0)
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, usage=Usage(input_tokens=1000, output_tokens=100), latency_ms=5)


def gateway(script, **kw):
    settings = Settings()
    router = ModelRouter.from_file(settings.models_config_path)
    prov = Scripted(script)
    sink = MemorySink()
    gw = build_gateway(sink, settings=settings, router=router, cache=MemoryCache(),
                       providers={"anthropic": prov, "deepseek": prov}, **kw)
    return gw, prov, sink


def run(gw, **kw):
    return gw.run(stage="analyze_job", label="it1:analyze_job", prompt_key="analyze_job",
                  payload={"job_text": "x"}, output=Out, **kw)


def test_schema_repair_then_success_records_each_attempt():
    gw, prov, sink = gateway({"claude-haiku-5-5": ['{"value": "nope"}', '{"value": 3}']})
    assert run(gw).value == 3
    assert [r.status for r in sink.records] == ["failed", "succeeded"]
    assert [r.attempt for r in sink.records] == [1, 2]
    assert sink.records[0].error_code == "schema_invalid"
    assert sink.records[1].estimated_cost_usd == pytest.approx((1000 * 0.10 + 100 * 0.50) / 1e6)


def test_failover_to_second_model_in_tier():
    gw, prov, sink = gateway({"claude-haiku-5-5": [ProviderError("down", code="http_503")],
                              "deepseek-chat": ['{"value": 7}']})
    assert run(gw).value == 7
    assert prov.calls == ["claude-haiku-5-5", "deepseek-chat"]
    assert "failover#1" in sink.records[-1].routing_reason


def test_escalation_uses_next_tier():
    gw, prov, sink = gateway({"claude-sonnet-5-5": ['{"value": 1}']})
    assert run(gw, escalate=1).value == 1
    assert sink.records[0].capability_tier == "medium"
    assert "escalated+1" in sink.records[0].routing_reason


def test_cache_hit_is_free_and_skips_provider():
    gw, prov, sink = gateway({"claude-haiku-5-5": ['{"value": 5}']})
    run(gw)
    run(gw)
    assert prov.calls == ["claude-haiku-5-5"]
    assert sink.records[-1].status == "cached" and sink.records[-1].estimated_cost_usd == 0


def test_all_models_down_raises():
    err = ProviderError("down", code="http_503")
    gw, prov, sink = gateway({"claude-haiku-5-5": [err], "deepseek-chat": [err]})
    with pytest.raises(AIUnavailable):
        run(gw)


def test_circuit_breaker_skips_open_model():
    err = ProviderError("down", code="http_503")
    gw, prov, sink = gateway({"claude-haiku-5-5": [err] * 3, "deepseek-chat": ['{"value": 1}'] * 4})
    for _ in range(3):
        gw.cache = MemoryCache()
        run(gw)
    gw.cache = MemoryCache()
    run(gw)
    assert prov.calls[-1] == "deepseek-chat" and prov.calls.count("claude-haiku-5-5") == 3
    assert "skipped_open=claude-haiku" in sink.records[-1].routing_reason


def test_enterprise_boost_starts_plan_higher():
    router = ModelRouter.from_file(Settings().models_config_path)
    assert router.tier_for("plan", customer_tier="enterprise")[0] == "high"
    assert router.tier_for("plan", escalate=5)[0] == "high"  # capped at max_tier
    assert router.tier_for("rewrite", escalate=5)[0] == "medium"
