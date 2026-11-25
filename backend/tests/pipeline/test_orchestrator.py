"""End-to-end pipeline tests on a generated DOCX with the offline provider.
Adversarial providers check that fabrication is caught, retried, escalated, and
finally reverted rather than shipped."""

import json

import pytest

from roletailor.ai.cache import MemoryCache
from roletailor.ai.gateway import AIUnavailable, build_gateway
from roletailor.ai.providers.fake import FakeProvider
from roletailor.ai.telemetry import MemorySink
from roletailor.config import Settings
from roletailor.documents import read_docx
from roletailor.domain.models import BlockPlan, BlockRewrite, RewriteBatch, TailoringPlan
from roletailor.pipeline.orchestrator import TailoringPrefs, tailor
from tests.fixtures.make_fixtures import make_classic_resume

JD = """Senior Machine Learning Engineer
Requirements: Python, Kubernetes, PostgreSQL, machine learning, MLOps, A/B testing, Airflow, Snowflake.
You will build forecasting systems and real-time features with Kafka and Spark."""


@pytest.fixture(scope="module")
def doc():
    data = make_classic_resume()
    return data, read_docx(data)


def _config(**routing):
    import yaml

    base = yaml.safe_load(Settings().models_config_path.read_text())
    return {**base, "routing": {**base["routing"], **routing}}


def run(doc, provider, routing=None, **kw):
    from roletailor.ai.router import ModelRouter

    sink = MemorySink()
    gw = build_gateway(sink, settings=Settings(llm_mode="fake"), cache=MemoryCache(),
                       providers={"anthropic": provider, "deepseek": provider},
                       router=ModelRouter(_config(**(routing or {}))))
    return tailor(document=doc[1], job_text=JD, prefs=TailoringPrefs(), gateway=gw, **kw), sink


def test_happy_path_offline(doc):
    result, sink = run(doc, FakeProvider())
    assert result.changes, "expected at least one faithful terminology change"
    assert all(c.block_path in result.edits for c in result.changes)
    assert "Snowflake" in result.plan.gaps
    assert result.feedback is not None
    stages = {r.stage.split(":")[1] for r in sink.records}
    assert stages == {"structure_resume", "analyze_job", "plan", "rewrite", "verify_claims", "feedback"}
    assert result.total_cost_usd == pytest.approx(sink.total_cost)


def test_cached_stages_are_skipped(doc):
    first, _ = run(doc, FakeProvider())
    _, sink = run(doc, FakeProvider(), cached_structure=first.structure, cached_job=first.job)
    assert not {"structure_resume", "analyze_job"} & {r.stage.split(":")[1] for r in sink.records}


class Fabricator(FakeProvider):
    """Plans every bullet, then rewrites by inventing a metric and a tool."""

    def _plan(self, p):
        bullets = [b["id"] for s in p["resume"]["sections"] if s["kind"] == "experience"
                   for b in s["blocks"] if b["editable"]]
        return TailoringPlan(block_plans=[BlockPlan(block_id=b, target_keywords=["Snowflake"])
                                          for b in bullets[:2]], confidence=0.9)

    def _rewrite(self, p):
        return RewriteBatch(rewrites=[
            BlockRewrite(block_id=b["block_id"], new_text=b["text"][:-1] + " on Snowflake, saving 25%.")
            for b in p["blocks"]])


def test_fabrication_is_retried_escalated_and_reverted(doc):
    prov = Fabricator()
    result, sink = run(doc, prov, routing={"rewrite_max_rounds": 3})
    assert result.edits == {} and result.changes == []
    rewrite_models = [m for m, k in prov.calls if k == "rewrite"]
    assert rewrite_models[:2] == ["claude-haiku-5-5", "claude-haiku-5-5"]
    assert rewrite_models[-1] == "claude-sonnet-5-5"  # third round escalates one tier
    by_rule = {v.rule_key: v for v in result.validations}
    assert by_rule["facts.numbers"].details["reverted_to_original"]
    assert by_rule["pipeline.coverage"].details["reverted_blocks"]


def test_feedback_is_sent_back_on_retry(doc):
    prov = Fabricator()
    seen = []
    original = prov.complete

    def spy(spec, req):
        if req.prompt_key == "rewrite":
            seen.append(json.loads(req.user).get("feedback"))
        return original(spec, req)

    prov.complete = spy
    run(doc, prov)
    assert seen[0] is None and seen[1], "second round must include rejection reasons"


class LiarVerifier(FakeProvider):
    def _verify_claims(self, p):
        out = super()._verify_claims(p)
        for r in out.results:
            r.supported, r.unsupported_claims = False, ["inflated scope"]
        return out


def test_claim_verifier_veto_reverts_edit(doc):
    result, _ = run(doc, LiarVerifier())
    assert result.edits == {}


def test_plan_outage_raises_for_clean_failure(doc):
    prov = FakeProvider(fail_models={"claude-sonnet-5-5", "deepseek-reasoner"})
    with pytest.raises(AIUnavailable):
        run(doc, prov)


def test_structure_outage_degrades_to_heuristics(doc):
    class NoStructure(FakeProvider):
        def complete(self, spec, req):
            if req.prompt_key == "structure_resume":
                from roletailor.ai.providers.base import ProviderError
                raise ProviderError("down", code="http_503")
            return super().complete(spec, req)

    result, _ = run(doc, NoStructure())
    assert any(v.rule_key == "pipeline.degraded" for v in result.validations)
    assert result.changes


def test_page_limit_reverts_growth(doc, monkeypatch):
    import roletailor.documents as d

    monkeypatch.setattr(d, "docx_to_pdf", lambda b: b)
    monkeypatch.setattr(d, "count_pdf_pages", lambda b: 3 if len(b) > len(doc[0]) else 1)
    monkeypatch.setattr(d, "apply_block_edits", lambda b, e: b + b"x" * sum(len(t) for t in e.values()))
    result, _ = run(doc, FakeProvider(), source_docx=doc[0])
    page = next(v for v in result.validations if v.rule_key == "layout.page_limit")
    assert page.details["reverted_blocks"] and result.edits == {}


class Unsure(FakeProvider):
    """Plans with low confidence; `rewrites` controls whether it proposes any edits."""

    def __init__(self, rewrites: bool):
        super().__init__()
        self.rewrites = rewrites

    def _plan(self, p):
        plan = super()._plan(p)
        plan.confidence = 0.3
        if not self.rewrites:
            plan.block_plans = []
        return plan


def test_low_confidence_plan_escalation_is_opt_in_and_skips_empty_plans(doc):
    import yaml

    from roletailor.ai.router import ModelRouter

    base = yaml.safe_load(Settings().models_config_path.read_text())
    on = {**base, "routing": {**base["routing"], "plan_escalate_on_low_confidence": True}}
    for cfg, rewrites, expected_plan_calls in ((base, True, 1), (on, True, 2), (on, False, 1)):
        prov = Unsure(rewrites)
        gw = build_gateway(MemorySink(), settings=Settings(llm_mode="fake"), cache=MemoryCache(),
                           providers={"anthropic": prov, "deepseek": prov}, router=ModelRouter(cfg))
        tailor(document=doc[1], job_text=JD, prefs=TailoringPrefs(), gateway=gw)
        assert sum(k == "plan" for _, k in prov.calls) == expected_plan_calls


def test_default_config_retries_once_without_escalating(doc):
    prov = Fabricator()
    result, _ = run(doc, prov)
    assert result.edits == {}
    assert [m for m, k in prov.calls if k == "rewrite"] == ["claude-haiku-5-5", "claude-haiku-5-5"]
