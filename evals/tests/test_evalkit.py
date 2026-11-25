"""Tests for the eval harness itself: a broken eval reports confident wrong numbers."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "evals")]

import gate  # noqa: E402
from evalkit import metrics  # noqa: E402
from evalkit.cases import load_cases  # noqa: E402
from evalkit.fingerprint import fingerprint  # noqa: E402
from validate_cases import problems  # noqa: E402

from roletailor.ai.cache import MemoryCache  # noqa: E402
from roletailor.ai.gateway import build_gateway  # noqa: E402
from roletailor.ai.telemetry import MemorySink  # noqa: E402
from roletailor.config import Settings  # noqa: E402
from roletailor.documents import read_docx  # noqa: E402
from roletailor.pipeline.orchestrator import TailoringPrefs, tailor  # noqa: E402


@pytest.fixture(scope="module")
def ml_case():
    case = next(c for c in load_cases() if c.name == "ml_engineer_strong_match")
    doc = read_docx(case.resume_bytes())
    gw = build_gateway(MemorySink(), settings=Settings(llm_mode="fake"), cache=MemoryCache())
    result = tailor(document=doc, job_text=case.job, gateway=gw, prefs=TailoringPrefs())
    return case, {b.id: b.text for b in doc.text_blocks()}, result


def test_case_set_is_large_and_valid():
    cases = load_cases()
    assert 25 <= len(cases) <= 60
    assert len({c.family for c in cases}) >= 10
    assert len({c.scenario for c in cases}) >= 12
    assert {c.seniority for c in cases} >= {"intern", "junior", "mid", "senior", "lead", "executive"}
    bad = {c.name: problems(c) for c in cases if problems(c)}
    assert not bad


def test_metrics_catch_canary_and_number_fabrication(ml_case):
    case, original, result = ml_case
    assert not metrics.compute(case, original, result, live=False).fabrications
    forged = copy.deepcopy(result)
    bid = next(b for b, t in original.items() if "Kafka" in t)
    forged.edits[bid] = original[bid] + " Migrated the warehouse to Snowflake for 37 teams."
    m = metrics.compute(case, original, forged, live=False)
    kinds = {(f["kind"], f["term"]) for f in m.fabrications}
    assert ("canary", "Snowflake") in kinds and ("number", "37") in kinds
    assert metrics.failures(case, m, live=False) == ["fabrication"]
    assert bid in m.length_outliers


def test_live_expectations_apply_only_live(ml_case):
    case, original, result = ml_case
    strict = case.model_copy(update={"expect": case.expect.model_copy(update={"live_min_changes": 99})})
    m = metrics.compute(strict, original, result, live=True)
    assert "too_few_changes" in metrics.failures(strict, m, live=True)
    assert "too_few_changes" not in metrics.failures(strict, m, live=False)


def _summary(**over):
    s = {"fabrication_cases": 0, "pass_rate": 0.95, "mean_cost_usd": 0.03, "p95_cost_usd": 0.05,
         "expected_gap_recall": 0.9, "errors": 0, "skipped": 0,
         "judge": {"truthfulness": 4.8, "truthfulness_below_4": 0}}
    s.update(over)
    return {"created_at": "2099-01-01T00:00:00Z", "fingerprint": fingerprint(),
            "configs": {"current": {"models": gate.production_models(), "summary": s}}}


def test_live_gate_thresholds():
    assert gate.check_live_summary(_summary()) == []
    assert any("fabricated" in p for p in gate.check_live_summary(_summary(fabrication_cases=1)))
    assert any("mean cost" in p for p in gate.check_live_summary(_summary(mean_cost_usd=0.2)))
    stale = _summary()
    stale["fingerprint"] = "0" * 16
    assert any("fingerprint" in p for p in gate.check_live_summary(stale))
    other = _summary()
    other["configs"]["current"]["models"] = {**gate.production_models(), "plan": "claude-haiku-5-5"}
    assert any("production config" in p for p in gate.check_live_summary(other))


def test_relative_config_paths_resolve_from_any_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RT_MODELS_CONFIG_PATH", "config/models.yaml")
    assert Settings().models_config_path == ROOT / "config" / "models.yaml"
    assert Settings().models_config_path.is_file()
