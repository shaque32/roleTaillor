"""Tests for the gold set logic. No network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "evals")]

import run_gold  # noqa: E402
from evalkit import gold  # noqa: E402


def test_bias_mad_within():
    j, h = [3.0, 4.0, 2.0], [4.0, 4.0, 5.0]
    assert gold.bias(j, h) == pytest.approx(-1.333, abs=1e-3)
    assert gold.mean_abs_diff(j, h) == pytest.approx(1.333, abs=1e-3)
    assert gold.share_within(j, h) == pytest.approx(0.667, abs=1e-3)
    assert gold.bias([], []) is None


def test_spearman_perfect_inverse_and_ties():
    assert gold.spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == 1.0
    assert gold.spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == -1.0
    # ties get average ranks; result is a known value
    assert gold.spearman([1, 1, 2, 3, 3], [1, 2, 2, 3, 3]) == pytest.approx(0.917, abs=1e-3)


def test_spearman_degenerate():
    assert gold.spearman([1, 2, 3, 4], [1, 2, 3, 4]) is None       # n < 5
    assert gold.spearman([3, 3, 3, 3, 3], [1, 2, 3, 4, 5]) is None  # no variance
    with pytest.raises(ValueError):
        gold.spearman([1, 2], [1])


def test_align_paragraphs_pairs_changed_only():
    orig = ["Summary", "Built dashboards for ops.", "Managed a team of four.", "Education"]
    human = ["Summary", "Built logistics dashboards for operations teams.", "Managed a team of four.",
             "Education", "A brand new paragraph about something else entirely."]
    edits = gold.align_paragraphs(orig, human)
    assert edits == [{"before": "Built dashboards for ops.",
                      "after": "Built logistics dashboards for operations teams."}]


def test_align_paragraphs_unrelated_replacement_is_not_an_edit():
    assert gold.align_paragraphs(["aaaa bbbb"], ["zzzz qqqq"]) == []
    assert gold.align_paragraphs(["same"], ["same"]) == []


def test_ratings_validation(tmp_path):
    ok = tmp_path / "r.yaml"
    ok.write_text("changes_hash: abc\nscores: {truthfulness: 5, relevance: 3}\naccept: {p3: true}\n")
    r = gold.load_ratings(ok)
    assert r.scores.relevance == 3 and r.scores.voice is None and r.accept == {"p3": True}
    for bad in ("scores: {relevance: 6}\n", "scores: {relevance: 0}\n", "bogus: 1\n", "scores: [1]\n"):
        ok.write_text(bad)
        with pytest.raises(ValueError):
            gold.load_ratings(ok)


def test_template_is_valid_ratings_and_carries_hash():
    changes = [{"block_id": "p3", "original": "a", "proposed": "b", "reason": "r"}]
    digest = gold.changes_hash(changes)
    import yaml
    data = yaml.safe_load(gold.ratings_template(changes, digest))
    r = gold.Ratings.model_validate(data)
    assert r.changes_hash == digest and r.accept == {"p3": None}
    # empty change list still yields valid yaml
    gold.Ratings.model_validate(yaml.safe_load(gold.ratings_template([], digest)))


def test_hash_changes_with_content_not_key_order():
    a = [{"block_id": "p1", "original": "x", "proposed": "y", "reason": "z"}]
    b = [{"reason": "z", "proposed": "y", "original": "x", "block_id": "p1"}]
    assert gold.changes_hash(a) == gold.changes_hash(b)
    assert gold.changes_hash(a) != gold.changes_hash([{**a[0], "proposed": "yy"}])


def _make_case(root: Path, name: str, judge: dict, scores: dict, *, stale=False, accept=None,
               judge_human: dict | None = None):
    out = root / name / "output"
    out.mkdir(parents=True)
    changes = [{"block_id": "p1", "original": "x", "proposed": "y", "reason": "z"},
               {"block_id": "p2", "original": "x2", "proposed": "y2", "reason": "z"}]
    digest = gold.changes_hash(changes)
    (out / "changes.json").write_text(json.dumps(changes))
    (out / "judge.json").write_text(json.dumps({**judge, "changes_hash": digest}))
    if judge_human:
        (out / "judge_human.json").write_text(json.dumps(judge_human))
    lines = [f"changes_hash: {'deadbeef' if stale else digest}", "scores:"]
    lines += [f"  {k}: {v}" for k, v in scores.items()]
    lines += ["accept:"] + [f"  {k}: {str(v).lower()}" for k, v in (accept or {}).items()]
    (root / name / "ratings.yaml").write_text("\n".join(lines) + "\n")


def _j(t, rel, rd=4, v=4):
    return {"truthfulness": t, "relevance": rel, "readability": rd, "voice": v}


def test_calibrate_end_to_end(tmp_path):
    for i, (jr, hr) in enumerate([(2, 4), (3, 5), (1, 3), (2, 4), (3, 4), (2, 5)]):
        _make_case(tmp_path, f"c{i}", _j(5, jr), _j(5, hr), accept={"p1": True, "p2": i % 2 == 0},
                   judge_human=_j(5, 3))
    _make_case(tmp_path, "stale_one", _j(5, 1), _j(5, 5), stale=True)
    _make_case(tmp_path, "_example", _j(5, 1), _j(5, 5))
    (tmp_path / "no_ratings").mkdir()
    r = gold.calibrate(tmp_path)
    assert r["n_cases"] == 6 and not r["enough_cases"]
    assert any("stale_one" in w and "stale" in w for w in r["warnings"])
    rel = r["dimensions"]["relevance"]
    assert rel["n"] == 6 and rel["bias"] == pytest.approx(-2.0, abs=1e-3)
    assert rel["spearman"] is not None
    assert r["dimensions"]["truthfulness"]["bias"] == 0.0
    assert r["dimensions"]["truthfulness"]["spearman"] is None  # zero variance
    assert r["human_accept_rate"] == pytest.approx(9 / 12, abs=1e-3)  # p1 always, p2 on even i
    assert r["human_tailored"]["n"] == 6 and r["human_tailored"]["judge_on_human"]["relevance"] == 3.0
    text = " ".join(r["verdicts"])
    assert "relevance: judge is 2.0 points harsher" in text and "truthfulness: calibrated" in text
    md = gold.calibration_markdown(r)
    assert "Nothing below is conclusive" in md and "n/a" in md


def test_calibrate_cli_writes_report(tmp_path, monkeypatch):
    _make_case(tmp_path / "gold", "c0", _j(5, 2), _j(5, 4))
    monkeypatch.setattr(run_gold, "GOLD_DIR", tmp_path / "gold")
    out = tmp_path / "rep" / "calibration.md"
    assert run_gold.main(["calibrate", "--out", str(out)]) == 0
    assert out.is_file() and out.with_suffix(".json").is_file()


def test_run_requires_yes_and_key(monkeypatch, capsys):
    assert run_gold.main(["run"]) == 2
    monkeypatch.setattr(run_gold, "load_dotenv", lambda: None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert run_gold.main(["run", "--yes"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out


def test_find_cases_and_example_parses(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "_ex").mkdir()
    assert [p.name for p in run_gold.find_cases(tmp_path, None)] == ["a"]
    assert [p.name for p in run_gold.find_cases(tmp_path, ["_ex"])] == ["_ex"]
    example = ROOT / "evals" / "gold" / "_example"
    doc, data = run_gold.parse_resume(run_gold.resume_file(example))
    assert data and any("Northwind" in b.text for b in doc.text_blocks())
    human = run_gold.human_paragraphs(example)
    edits = gold.align_paragraphs([b.text for b in doc.text_blocks()], human)
    assert edits  # the example human version changes some bullets


def test_review_markdown_lists_changes_and_gaps():
    md = run_gold.review_markdown("c", [{"block_id": "p1", "original": "a", "proposed": "b", "reason": "r"}],
                                  ["Kubernetes"])
    assert "**Original:** a" in md and "**Proposed:** b" in md and "- Kubernetes" in md
