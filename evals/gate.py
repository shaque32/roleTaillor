"""Release gate for prompt, model, and validation changes.

    python ../evals/gate.py offline                 # run offline evals, compare to the baseline
    python ../evals/gate.py offline --update        # accept the current offline results as baseline
    python ../evals/gate.py live-evidence --base origin/feat/tailoring-mvp

`offline` is free and deterministic; CI runs it on every pull request. It fails on any
fabrication, any failing case, a per-case drop in accepted changes or keyword coverage,
or an estimated cost increase past the threshold in gate.yaml.

`live-evidence` makes real-model evidence mandatory for behaviour changes. If the diff
against --base touches config/models.yaml, a prompt, or a validation rule, the committed
evals/results/live_summary.json must carry the current behaviour fingerprint (so it was
produced from this exact code) and meet the live thresholds for the production config.
Produce it with:  make eval-live   (then commit evals/results/live_summary.json)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "evals")]

from evalkit.fingerprint import INPUTS, fingerprint  # noqa: E402

RESULTS = ROOT / "evals" / "results"
BASELINE = RESULTS / "offline_baseline.json"
LIVE = RESULTS / "live_summary.json"
THRESHOLDS = yaml.safe_load((ROOT / "evals" / "gate.yaml").read_text())


def _run_offline() -> dict:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "report.json"
        subprocess.run([sys.executable, str(ROOT / "evals" / "run_evals.py"), "--out", str(out)],
                       cwd=ROOT / "backend", check=False, stdout=subprocess.DEVNULL)
        if not out.exists():
            raise SystemExit("offline eval run did not produce a report")
        return json.loads(out.read_text())


def _baseline_view(report: dict) -> dict:
    cfg = report["configs"]["current"]
    return {"fingerprint": report["fingerprint"], "summary": {
                k: cfg["summary"][k] for k in ("cases", "pass_rate", "fabrications", "mean_cost_usd",
                                               "mean_changes", "mean_coverage_after")},
            "cases": {r["case"]: {"status": r["status"], "passed": r.get("passed"), "changes": r.get("changes"),
                                  "coverage_after": r.get("coverage_after"), "cost_usd": r.get("cost_usd")}
                      for r in sorted(cfg["results"], key=lambda r: r["case"])}}


def offline(update: bool) -> int:
    t = THRESHOLDS["offline"]
    now = _baseline_view(_run_offline())
    if update:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(now, indent=2) + "\n")
        print(f"Wrote {BASELINE.relative_to(ROOT)} ({now['summary']['cases']} cases).")
        return 0
    problems: list[str] = []
    s = now["summary"]
    if s["fabrications"] > t["max_fabrications"]:
        problems.append(f"{s['fabrications']} fabrications (max {t['max_fabrications']})")
    if s["pass_rate"] < t["min_pass_rate"]:
        failed = [n for n, c in now["cases"].items() if not c["passed"]]
        problems.append(f"pass rate {s['pass_rate']} below {t['min_pass_rate']}: {failed}")
    if not BASELINE.exists():
        problems.append(f"no baseline; run `gate.py offline --update` and commit {BASELINE.relative_to(ROOT)}")
    else:
        base = json.loads(BASELINE.read_text())
        regress = []
        for name, b in base["cases"].items():
            c = now["cases"].get(name)
            if c is None:
                problems.append(f"case {name} is in the baseline but no longer runs")
                continue
            if b["status"] == "ok" and c["status"] != "ok":
                regress.append(f"{name}: now errors")
            elif (c["changes"] or 0) < (b["changes"] or 0):
                regress.append(f"{name}: changes {b['changes']} -> {c['changes']}")
            elif (c["coverage_after"] or 0) + 0.05 < (b["coverage_after"] or 0):
                regress.append(f"{name}: coverage {b['coverage_after']} -> {c['coverage_after']}")
        if len(regress) > t["allow_change_regressions"]:
            problems.append("per-case regressions: " + "; ".join(regress))
        b_cost, c_cost = base["summary"]["mean_cost_usd"], s["mean_cost_usd"]
        same_cases = set(base["cases"]) == set(now["cases"])
        if same_cases and b_cost and (c_cost - b_cost) / b_cost * 100 > t["max_cost_increase_pct"]:
            problems.append(f"estimated cost per run up {100 * (c_cost - b_cost) / b_cost:.1f}% "
                            f"(${b_cost:.5f} -> ${c_cost:.5f}); max {t['max_cost_increase_pct']}%")
        new = sorted(set(now["cases"]) - set(base["cases"]))
        if new:
            print(f"note: {len(new)} new cases not in the baseline yet: {new}. Run with --update to add them.")
    print(f"offline: {s['cases']} cases, pass rate {s['pass_rate']}, fabrications {s['fabrications']}, "
          f"est. ${s['mean_cost_usd']:.5f}/run")
    for p in problems:
        print(f"FAIL {p}")
    return 1 if problems else 0


def _changed_behaviour_files(base: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD", "--", *INPUTS],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [x for x in out.splitlines() if x]


def production_models() -> dict[str, str]:
    cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text())
    return {s: cfg["models"][cfg["tiers"][p["tier"]][0]]["model"] for s, p in cfg["stages"].items()}


def check_live_summary(summary: dict) -> list[str]:
    t = THRESHOLDS["live"]
    problems = []
    if summary["fingerprint"] != fingerprint():
        problems.append(f"live summary fingerprint {summary['fingerprint']} does not match the code "
                        f"({fingerprint()}); re-run `make eval-live` and commit the new summary")
    prod = production_models()
    cfg = next((c for c in summary["configs"].values() if c["models"] == prod), None)
    if cfg is None:
        return [*problems, f"live summary has no run of the production config {prod}"]
    s = cfg["summary"]
    checks = [
        (s["fabrication_cases"] <= t["max_fabrication_cases"], f"{s['fabrication_cases']} cases fabricated"),
        (s["pass_rate"] >= t["min_pass_rate"], f"pass rate {s['pass_rate']} < {t['min_pass_rate']}"),
        (s["mean_cost_usd"] <= t["max_mean_cost_usd"], f"mean cost ${s['mean_cost_usd']} > ${t['max_mean_cost_usd']}"),
        (s["p95_cost_usd"] <= t["max_p95_cost_usd"], f"p95 cost ${s['p95_cost_usd']} > ${t['max_p95_cost_usd']}"),
        (s["expected_gap_recall"] is None or s["expected_gap_recall"] >= t["min_expected_gap_recall"],
         f"gap recall {s['expected_gap_recall']} < {t['min_expected_gap_recall']}"),
        (s["errors"] == 0 and s["skipped"] == 0, f"{s['errors']} errors, {s['skipped']} skipped"),
    ]
    if j := s.get("judge"):
        checks += [(j["truthfulness"] >= t["min_judge_truthfulness"],
                    f"judge truthfulness {j['truthfulness']} < {t['min_judge_truthfulness']}"),
                   (j["truthfulness_below_4"] <= t["max_judge_truthfulness_below_4"],
                    f"{j['truthfulness_below_4']} cases judged truthfulness below 4")]
    problems += [msg for ok, msg in checks if not ok]
    age = (datetime.now(UTC) - datetime.strptime(summary["created_at"], "%Y-%m-%dT%H:%M:%SZ")
           .replace(tzinfo=UTC)).days
    if age > t["max_summary_age_days"]:
        problems.append(f"live summary is {age} days old")
    return problems


def live_evidence(base: str) -> int:
    changed = _changed_behaviour_files(base)
    if not changed:
        print("No prompt, model, or validation changes; live evidence not required.")
        return 0
    print("Behaviour changes:\n  " + "\n  ".join(changed))
    if not LIVE.exists():
        print(f"FAIL these changes need a live eval. Run `make eval-live` and commit {LIVE.relative_to(ROOT)}.")
        return 1
    problems = check_live_summary(json.loads(LIVE.read_text()))
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        print("Live summary matches this code and meets the thresholds.")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("offline")
    o.add_argument("--update", action="store_true")
    le = sub.add_parser("live-evidence")
    le.add_argument("--base", required=True, help="git ref the PR merges into")
    args = ap.parse_args()
    return offline(args.update) if args.cmd == "offline" else live_evidence(args.base)


if __name__ == "__main__":
    raise SystemExit(main())
