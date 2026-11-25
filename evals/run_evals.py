"""RoleTailor eval harness.

Runs every case in evals/cases through the real pipeline and scores the output with
checks that do not trust the pipeline's own validators:

- fabrication: canary terms (job keywords the resume lacks) or numbers that appear in
  the output but not the original. Target: zero, always.
- keyword coverage before and after, number of accepted changes, reverted blocks.
- cost and latency per stage, from the same telemetry that feeds ai_metrics.

Usage (from backend/ with the venv active):
    python ../evals/run_evals.py                      # offline, deterministic provider
    python ../evals/run_evals.py --live --yes         # real models; costs money
    python ../evals/run_evals.py --live --yes --stage-tier plan=low   # compare a cheaper plan stage

Writes evals/reports/<timestamp>.json and prints a summary table.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from roletailor.ai.cache import MemoryCache  # noqa: E402
from roletailor.ai.gateway import build_gateway  # noqa: E402
from roletailor.ai.router import ModelRouter  # noqa: E402
from roletailor.ai.telemetry import MemorySink  # noqa: E402
from roletailor.config import Settings  # noqa: E402
from roletailor.documents import read_docx  # noqa: E402
from roletailor.pipeline import scoring  # noqa: E402
from roletailor.pipeline.orchestrator import TailoringPrefs, tailor  # noqa: E402
from roletailor.pipeline.text import bare_numbers, contains_term  # noqa: E402
from roletailor.redaction import redact  # noqa: E402
from tests.fixtures.make_fixtures import (  # noqa: E402
    make_classic_resume,
    make_table_resume,
)

RESUMES = {"classic": make_classic_resume, "table": make_table_resume}


def load_resume(ref: str) -> bytes:
    if ref in RESUMES:
        return RESUMES[ref]()
    return (ROOT / "evals" / "cases" / ref).read_bytes()


def run_case(case: dict, *, settings: Settings, router: ModelRouter, render: bool) -> dict:
    data = load_resume(case["resume"])
    doc = read_docx(data)
    sink = MemorySink()
    gw = build_gateway(sink, settings=settings, router=router, cache=MemoryCache())
    started = time.monotonic()
    result = tailor(document=doc, job_text=case["job"], gateway=gw,
                    prefs=TailoringPrefs(page_limit=case.get("page_limit", 2)),
                    source_docx=data if render else None)
    elapsed = time.monotonic() - started

    by_id = {b.id: b.text for b in doc.blocks}
    fabrications = []
    for bid, new in result.edits.items():
        orig = by_id[bid]
        for term in case.get("canaries", []):
            if contains_term(new, term) and not contains_term(orig, term):
                fabrications.append({"block": bid, "kind": "canary", "term": term})
        for n in bare_numbers(new) - bare_numbers(orig):
            fabrications.append({"block": bid, "kind": "number", "term": n})

    before = scoring.keyword_report("\n".join(by_id.values()), result.job)
    after = scoring.keyword_report("\n".join(result.edits.get(k, v) for k, v in by_id.items()), result.job)
    coverage = next((v for v in result.validations if v.rule_key == "pipeline.coverage"), None)
    expect = case.get("expect", {})
    failures = []
    if fabrications:
        failures.append("fabrication")
    if len(result.changes) < expect.get("min_changes", 0):
        failures.append("too_few_changes")
    return {
        "case": case["name"],
        "passed": not failures,
        "failures": failures,
        "fabrications": fabrications,
        "changes": len(result.changes),
        "reverted": len(coverage.details["reverted_blocks"]) if coverage else 0,
        "coverage_before": round(before.coverage, 1),
        "coverage_after": round(after.coverage, 1),
        "ats_before": result.scores_before.ats,
        "ats_after": result.scores_after.ats,
        "gaps": result.plan.gaps,
        "cost_usd": round(sink.total_cost, 6),
        "cost_by_stage": {k: round(v, 6) for k, v in sink.by_stage().items()},
        "calls": len(sink.records),
        "cache_hits": sum(r.status == "cached" for r in sink.records),
        "latency_s": round(elapsed, 2),
        "examples": [{"before": c.prior_text, "after": c.proposed_text, "reason": c.reason}
                     for c in result.changes[:5]],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="call real providers (needs API keys)")
    ap.add_argument("--yes", action="store_true", help="confirm live spending")
    ap.add_argument("--stage-tier", action="append", default=[], metavar="STAGE=TIER",
                    help="override a stage's starting tier, e.g. plan=low")
    ap.add_argument("--render", action="store_true", help="run the LibreOffice page-limit check")
    ap.add_argument("--case", action="append", help="run only these case names")
    args = ap.parse_args()
    if args.live and not args.yes:
        print("Live evals call paid APIs. Re-run with --yes to confirm.")
        return 2

    settings = Settings(llm_mode="live" if args.live else "fake")
    config = yaml.safe_load(settings.models_config_path.read_text())
    for item in args.stage_tier:
        stage, tier = item.split("=", 1)
        config["stages"][stage]["tier"] = tier
    router = ModelRouter(config)

    cases = [yaml.safe_load(p.read_text()) for p in sorted((ROOT / "evals" / "cases").glob("*.yaml"))]
    if args.case:
        cases = [c for c in cases if c["name"] in args.case]
    results = [run_case(c, settings=settings, router=router, render=args.render) for c in cases]

    print(f"\n{'case':34} {'pass':5} {'chg':>4} {'rev':>4} {'kw before':>9} {'kw after':>8} "
          f"{'fab':>4} {'cost $':>9}")
    for r in results:
        print(f"{r['case']:34} {'yes' if r['passed'] else 'NO':5} {r['changes']:>4} {r['reverted']:>4} "
              f"{r['coverage_before']:>9} {r['coverage_after']:>8} {len(r['fabrications']):>4} "
              f"{r['cost_usd']:>9.5f}")
    total = sum(r["cost_usd"] for r in results)
    print(f"\nmode={'live' if args.live else 'offline'} cases={len(results)} "
          f"avg_cost_per_generation=${total / max(len(results), 1):.5f}")

    out_dir = ROOT / "evals" / "reports"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {"mode": "live" if args.live else "offline", "stage_tiers": config["stages"],
              "results": results}
    # Reports hold model output and error text; mask any credential before it touches disk.
    (out_dir / f"{stamp}.json").write_text(redact(json.dumps(report, indent=2)))
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
