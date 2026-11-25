"""RoleTailor eval harness.

Runs every case in evals/cases through the real pipeline and scores the output with
checks that do not trust the pipeline's own validators (see evalkit/metrics.py):
fabrication (canary terms and new numbers), ATS keyword coverage before and after,
length drift, honest gap reporting, cost and latency per stage, and, for live runs,
an LLM judge on truthfulness, relevance, readability, and voice.

Usage (from backend/ with the venv active, or use the Makefile targets):
    python ../evals/run_evals.py                          # offline, deterministic, free
    python ../evals/run_evals.py --live --yes             # real models, current config
    python ../evals/run_evals.py --live --yes --compare-plan --judge   # Sonnet vs Haiku planning
    python ../evals/run_evals.py --live --yes --config cheap=plan=low,verify_claims=low

Live runs read ANTHROPIC_API_KEY (and DEEPSEEK_API_KEY for failover) from the
environment or from .env at the repo root or backend/. Spending stops at --max-usd.

Writes evals/reports/<timestamp>/report.json and report.md. --save-summary also writes
evals/results/live_summary.json, the committed record CI checks against.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "evals")]

from evalkit import metrics, safe_write  # noqa: E402
from evalkit.cases import EvalCase, load_cases  # noqa: E402
from evalkit.fingerprint import fingerprint  # noqa: E402

from roletailor.ai.cache import MemoryCache  # noqa: E402
from roletailor.ai.gateway import AIUnavailable, build_gateway  # noqa: E402
from roletailor.ai.router import ModelRouter  # noqa: E402
from roletailor.ai.telemetry import MemorySink  # noqa: E402
from roletailor.config import Settings  # noqa: E402
from roletailor.documents import read_docx  # noqa: E402
from roletailor.pipeline.orchestrator import TailoringPrefs, tailor  # noqa: E402

TARGET_COST_PER_RUN = 0.04  # USD, the planning estimate in docs/architecture.md
REPORTS = ROOT / "evals" / "reports"
SUMMARY = ROOT / "evals" / "results" / "live_summary.json"


# --------------------------------------------------------------------------- config


def load_dotenv() -> None:
    """Fill missing provider API keys from .env files. Values are never printed. Other
    settings (RT_*) are read by Settings itself."""
    for path in (ROOT / ".env", ROOT / "backend" / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.split(" #", 1)[0].strip().strip('"').strip("'")
            if v and k.strip().endswith("_API_KEY") and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v


def parse_config(spec: str) -> tuple[str, dict[str, str]]:
    """'cheap=plan=low,rewrite=low' -> ('cheap', {'plan': 'low', 'rewrite': 'low'})."""
    name, _, rest = spec.partition("=")
    tiers = {}
    for item in filter(None, rest.split(",")):
        stage, _, tier = item.partition("=")
        tiers[stage.strip()] = tier.strip()
    return name.strip(), tiers


def router_config(base: dict, tiers: dict[str, str]) -> dict:
    cfg = deepcopy(base)
    for stage, tier in tiers.items():
        if stage not in cfg["stages"] or tier not in cfg["tiers"]:
            raise SystemExit(f"unknown stage or tier in override: {stage}={tier}")
        cfg["stages"][stage]["tier"] = tier
        order = ["low", "medium", "high"]
        if order.index(cfg["stages"][stage].get("max_tier", tier)) < order.index(tier):
            cfg["stages"][stage]["max_tier"] = tier
    return cfg


def describe(cfg: dict) -> dict[str, str]:
    """Stage -> first model in its starting tier, e.g. {'plan': 'claude-sonnet-5-5'}."""
    return {s: cfg["models"][cfg["tiers"][p["tier"]][0]]["model"] for s, p in cfg["stages"].items()}


def build_judge_ctx(base: dict, judge_model: str) -> dict:
    """Provider and model spec for the LLM judge. Needs ANTHROPIC_API_KEY in the environment."""
    from roletailor.ai.providers.anthropic_provider import AnthropicProvider

    spec = ModelRouter(base).models[judge_model]
    return {"provider": AnthropicProvider(api_key=os.environ["ANTHROPIC_API_KEY"]), "spec": spec}


# --------------------------------------------------------------------------- one case


class Budget:
    def __init__(self, limit: float):
        self.limit, self.spent, self._lock = limit, 0.0, threading.Lock()

    def add(self, usd: float) -> None:
        with self._lock:
            self.spent += usd

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit


def run_case(case: EvalCase, *, cfg: dict, settings: Settings, live: bool, render: bool,
             judge_ctx: dict | None, budget: Budget) -> dict:
    row: dict = {"case": case.name, "family": case.family, "seniority": case.seniority,
                 "scenario": case.scenario}
    if budget.exhausted:
        return {**row, "status": "skipped", "error": "budget exhausted"}
    data = case.resume_bytes()
    doc = read_docx(data)
    original = {b.id: b.text for b in doc.text_blocks()}
    sink = MemorySink()
    # A fresh router per case keeps circuit-breaker state from leaking between cases.
    gw = build_gateway(sink, settings=settings, router=ModelRouter(cfg), cache=MemoryCache())
    started = time.monotonic()
    try:
        result = tailor(document=doc, job_text=case.job, gateway=gw,
                        prefs=TailoringPrefs(page_limit=case.page_limit),
                        source_docx=data if render else None)
    except AIUnavailable as e:
        budget.add(sink.total_cost)
        return {**row, "status": "error", "error": f"AIUnavailable: {e}", "cost_usd": sink.total_cost,
                "calls": _calls(sink)}
    except Exception as e:  # noqa: BLE001 - a harness or pipeline crash is an error, not a model failure
        budget.add(sink.total_cost)
        return {**row, "status": "error", "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(limit=5), "cost_usd": sink.total_cost}
    elapsed = time.monotonic() - started
    budget.add(sink.total_cost)

    m = metrics.compute(case, original, result, live=live)
    fails = metrics.failures(case, m, live=live)
    row.update({
        "status": "ok", "passed": not fails, "failures": fails,
        "expected_gaps": case.expect.live_expected_gaps if live else [],
        **{k: v for k, v in m.__dict__.items()},
        "cost_usd": round(sink.total_cost, 6),
        "cost_by_stage": {k: round(v, 6) for k, v in sink.by_stage().items()},
        "latency_s": round(elapsed, 2),
        "latency_by_stage_s": _latency_by_stage(sink),
        "calls": _calls(sink),
        "escalated_stages": sorted({r.stage.split(":")[1] for r in sink.records
                                    if "escalated" in r.routing_reason and r.status != "cached"}),
        "models_used": sorted({f"{r.stage.split(':')[1]}:{r.model_name}" for r in sink.records
                               if r.status == "succeeded"}),
        "examples": [{"block": c.block_path, "before": c.prior_text, "after": c.proposed_text,
                      "reason": c.reason} for c in result.changes[:8]],
    })
    if judge_ctx and not budget.exhausted:
        from evalkit.judge import judge

        try:
            verdict, cost = judge(judge_ctx["provider"], judge_ctx["spec"], job=case.job,
                                  resume_text="\n".join(original.values()),
                                  edits=[{"before": c.prior_text, "after": c.proposed_text}
                                         for c in result.changes])
            budget.add(cost)
            row["judge"], row["judge_cost_usd"] = verdict, round(cost, 6)
        except Exception as e:  # noqa: BLE001 - a judge failure never fails the case
            row["judge_error"] = f"{type(e).__name__}: {e}"[:300]
    return row


def _latency_by_stage(sink: MemorySink) -> dict[str, float]:
    """Summed model time per stage. Rewrite batches run in parallel, so their sum can
    exceed wall time; the order still shows where the time goes."""
    out: dict[str, float] = {}
    for r in sink.records:
        key = r.stage.split(":", 2)[1] if ":" in r.stage else r.stage
        out[key] = round(out.get(key, 0.0) + r.latency_ms / 1000, 2)
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _calls(sink: MemorySink) -> dict:
    statuses: dict[str, int] = {}
    for r in sink.records:
        statuses[r.status] = statuses.get(r.status, 0) + 1
    return statuses


# --------------------------------------------------------------------------- aggregate


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))], 6)


def aggregate(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["status"] == "ok"]
    costs = [r["cost_usd"] for r in ok]
    lat = [r["latency_s"] for r in ok]
    stages: dict[str, list[float]] = {}
    for r in ok:
        for s, c in r["cost_by_stage"].items():
            stages.setdefault(s, []).append(c)
    fail_counts: dict[str, int] = {}
    for r in ok:
        for f in r["failures"]:
            fail_counts[f] = fail_counts.get(f, 0) + 1
    by_scenario: dict[str, list[bool]] = {}
    for r in ok:
        by_scenario.setdefault(r["scenario"], []).append(r["passed"])
    judged = [r["judge"] for r in ok if "judge" in r]
    out = {
        "cases": len(rows), "scored": len(ok),
        "errors": sum(r["status"] == "error" for r in rows),
        "skipped": sum(r["status"] == "skipped" for r in rows),
        "pass_rate": round(sum(r["passed"] for r in ok) / len(ok), 4) if ok else 0.0,
        "fabrication_cases": sum(bool(r["fabrications"]) for r in ok),
        "fabrications": sum(len(r["fabrications"]) for r in ok),
        "fabrication_rate": round(sum(bool(r["fabrications"]) for r in ok) / len(ok), 4) if ok else 0.0,
        "mean_changes": round(statistics.mean(r["changes"] for r in ok), 2) if ok else 0.0,
        "mean_reverted": round(statistics.mean(r["reverted"] for r in ok), 2) if ok else 0.0,
        "mean_coverage_before": round(statistics.mean(r["coverage_before"] for r in ok), 2) if ok else 0.0,
        "mean_coverage_after": round(statistics.mean(r["coverage_after"] for r in ok), 2) if ok else 0.0,
        "mean_coverage_gain": round(statistics.mean(r["coverage_after"] - r["coverage_before"] for r in ok), 2)
        if ok else 0.0,
        "mean_planned_blocks": round(statistics.mean(r["planned_blocks"] for r in ok), 2) if ok else 0.0,
        "zero_change_rate": round(sum(r["changes"] == 0 for r in ok) / len(ok), 3) if ok else 0.0,
        "mean_no_gain_skipped": round(statistics.mean(r["no_gain_skipped"] for r in ok), 2) if ok else 0.0,
        "mean_exact_term_gain": round(statistics.mean(
            r["exact_coverage_after"] - r["exact_coverage_before"] for r in ok), 2) if ok else 0.0,
        "plan_escalation_rate": round(sum("plan" in r["escalated_stages"] for r in ok) / len(ok), 3) if ok else 0.0,
        "rewrite_escalation_rate": round(sum("rewrite" in r["escalated_stages"] for r in ok) / len(ok), 3)
        if ok else 0.0,
        "expected_gap_recall": _gap_recall(ok),
        "length_outlier_blocks": sum(len(r["length_outliers"]) for r in ok),
        "max_length_drift": max((r["max_length_drift"] for r in ok), default=0.0),
        "unexpected_terms": sum(len(r["unexpected_terms"]) for r in ok),
        "mean_cost_usd": round(statistics.mean(costs), 6) if costs else 0.0,
        "p50_cost_usd": _pct(costs, 0.5), "p95_cost_usd": _pct(costs, 0.95),
        "max_cost_usd": round(max(costs), 6) if costs else 0.0,
        "gate_hits_per_run": _gate_hits(ok),
        "mean_cost_by_stage": {s: round(sum(v) / len(ok), 6) for s, v in sorted(stages.items())},
        "mean_latency_by_stage_s": _mean_latency(ok),
        "p50_latency_s": _pct(lat, 0.5), "p95_latency_s": _pct(lat, 0.95),
        "failure_counts": dict(sorted(fail_counts.items())),
        "pass_rate_by_scenario": {k: round(sum(v) / len(v), 2) for k, v in sorted(by_scenario.items())},
        "judge_cost_usd": round(sum(r.get("judge_cost_usd", 0.0) for r in ok), 6),
    }
    if judged:
        out["judge"] = {k: round(statistics.mean(j[k] for j in judged), 2)
                        for k in ("truthfulness", "relevance", "readability", "voice")}
        out["judge"]["n"] = len(judged)
        out["judge"]["truthfulness_below_4"] = sum(j["truthfulness"] < 4 for j in judged)
    return out


def _gate_hits(rows: list[dict]) -> dict[str, float]:
    tot: dict[str, int] = {}
    for r in rows:
        for k, v in r.get("gate_hits", {}).items():
            tot[k] = tot.get(k, 0) + v
    return {k: round(v / len(rows), 2) for k, v in sorted(tot.items(), key=lambda kv: -kv[1])} if rows else {}


def _mean_latency(rows: list[dict]) -> dict[str, float]:
    tot: dict[str, float] = {}
    for r in rows:
        for s, v in r.get("latency_by_stage_s", {}).items():
            tot[s] = tot.get(s, 0.0) + v
    return {s: round(v / len(rows), 2) for s, v in sorted(tot.items(), key=lambda kv: -kv[1])} if rows else {}


def _gap_recall(rows: list[dict]) -> float | None:
    """Share of the must-have gaps the cases name that the plan reported to the user."""
    want = sum(len(r["expected_gaps"]) for r in rows)
    got = sum(len(r["expected_gaps"]) - len(r["expected_gaps_missed"]) for r in rows)
    return round(got / want, 3) if want else None


# --------------------------------------------------------------------------- report


def markdown(report: dict) -> str:
    lines = [f"# RoleTailor eval report, {report['created_at']}", "",
             f"Mode: **{report['mode']}**. Cases: {report['case_count']}. Reps: {report['reps']}. "
             f"Behaviour fingerprint: `{report['fingerprint']}`. Total spend: ${report['total_spend_usd']:.4f}.", ""]
    cols = ["pass_rate", "fabrication_cases", "errors", "mean_planned_blocks", "mean_changes", "zero_change_rate",
            "mean_no_gain_skipped", "mean_reverted",
            "mean_exact_term_gain",
            "expected_gap_recall", "plan_escalation_rate", "rewrite_escalation_rate",
            "length_outlier_blocks", "mean_cost_usd", "p95_cost_usd", "p50_latency_s",
            "p95_latency_s"]
    names = list(report["configs"])
    lines += ["| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for c in cols:
        lines.append(f"| {c} | " + " | ".join(str(report["configs"][n]["summary"].get(c)) for n in names) + " |")
    if any("judge" in report["configs"][n]["summary"] for n in names):
        for k in ("truthfulness", "relevance", "readability", "voice", "truthfulness_below_4"):
            lines.append(f"| judge.{k} | " + " | ".join(
                str(report["configs"][n]["summary"].get("judge", {}).get(k, "")) for n in names) + " |")
    lines.append("")
    for n in names:
        s = report["configs"][n]["summary"]
        lines.append(f"**{n}** starting models: " + ", ".join(
            f"{k}={v}" for k, v in report["configs"][n]["models"].items()))
        target = ("not measured (no scored runs)" if not s["scored"]
                  else "met" if s["mean_cost_usd"] <= TARGET_COST_PER_RUN else "NOT met")
        lines.append(f"Mean model time by stage (s): {s['mean_latency_by_stage_s']}.")
        lines.append(f"Blocks rejected by each gate, per run (these trigger rewrite retries): "
                     f"{s['gate_hits_per_run']}.")
        lines.append(f"Mean cost by stage: {s['mean_cost_by_stage']}. "
                     f"Target ${TARGET_COST_PER_RUN:.2f}/run: {target}.")
        bad = [r for r in report["configs"][n]["results"] if r["status"] != "ok" or not r["passed"]]
        for r in bad:
            why = r.get("error") or ", ".join(r["failures"])
            extra = f" fabrications={r['fabrications']}" if r.get("fabrications") else ""
            if r.get("expected_gaps_missed"):
                extra += f" missed={r['expected_gaps_missed']} reported={r['gaps_reported']}"
            lines.append(f"- {r['case']} ({r['scenario']}): {why}{extra}")
        skipped = [(r["case"], e) for r in report["configs"][n]["results"]
                   for e in r.get("no_gain_examples", [])][:8]
        if skipped:
            lines += ["", "Edits dropped as cosmetic (first 8):"]
            lines += [f"- {c}: `{e['before'][:110]}` -> `{e['proposed'][:110]}`" for c, e in skipped]
        missed = [(r["case"], m) for r in report["configs"][n]["results"]
                  for m in r.get("judge", {}).get("missed_opportunities", [])][:10]
        if missed:
            lines += ["", "Judge: honest matches the edits did not surface (first 10):"]
            lines += [f"- {c}: {m[:220]}" for c, m in missed]
        flagged = [r for r in report["configs"][n]["results"]
                   if r.get("judge", {}).get("truthfulness", 5) < 4]
        if flagged:
            lines += ["", f"Judge flagged {len(flagged)} cases for truthfulness below 4:"]
            for r in flagged:
                j = r["judge"]
                lines.append(f"- {r['case']} (truthfulness {j['truthfulness']}): "
                             f"{'; '.join(j['unsupported_claims'][:3]) or j['rationale'][:200]}")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="call real providers (needs API keys)")
    ap.add_argument("--yes", action="store_true", help="confirm live spending")
    ap.add_argument("--config", action="append", default=[], metavar="NAME=STAGE=TIER[,STAGE=TIER]",
                    help="a named routing variant; repeat to compare. Default: the current config")
    ap.add_argument("--stage-tier", action="append", default=[], metavar="STAGE=TIER",
                    help="shorthand for one variant with these overrides")
    ap.add_argument("--compare-plan", action="store_true",
                    help="compare plan on the medium tier (Sonnet) against the low tier (Haiku)")
    ap.add_argument("--judge", action="store_true", help="score edits with an LLM judge (live only)")
    ap.add_argument("--judge-model", default="claude-sonnet", help="models.yaml key for the judge")
    ap.add_argument("--reps", type=int, default=1, help="repeat each case N times (live variance)")
    ap.add_argument("--max-usd", type=float, default=5.0, help="stop starting new cases past this spend")
    ap.add_argument("--concurrency", type=int, default=None, help="parallel cases (default 4 live, 1 offline)")
    ap.add_argument("--render", action="store_true", help="run the LibreOffice page-limit check")
    ap.add_argument("--case", action="append", help="run only these case names")
    ap.add_argument("--scenario", action="append", help="run only these scenarios")
    ap.add_argument("--family", action="append", help="run only these role families")
    ap.add_argument("--save-summary", action="store_true",
                    help=f"write {SUMMARY.relative_to(ROOT)} for CI (live runs only)")
    ap.add_argument("--out", type=Path, help="write report.json to this path instead")
    args = ap.parse_args()

    if args.live and not args.yes:
        print("Live evals call paid APIs (about $0.02 to $0.06 per case per config). Re-run with --yes.")
        return 2
    if args.judge and not args.live:
        print("--judge needs --live.")
        return 2
    if args.live:
        load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set. Add it to .env at the repo root (never commit it) "
                  "or export it, then re-run.")
            return 2

    settings = Settings(llm_mode="live" if args.live else "fake")
    base = yaml.safe_load(settings.models_config_path.read_text())
    variants: list[tuple[str, dict[str, str]]] = [parse_config(c) for c in args.config]
    if args.stage_tier:
        variants.append(("override", dict(x.split("=", 1) for x in args.stage_tier)))
    if args.compare_plan:
        variants += [("plan_sonnet", {"plan": "medium"}), ("plan_haiku", {"plan": "low"})]
    if not variants:
        variants = [("current", {})]

    cases = load_cases(names=args.case, scenarios=args.scenario, families=args.family)
    if not cases:
        print("no cases matched")
        return 2
    budget = Budget(args.max_usd if args.live else float("inf"))
    judge_ctx = None
    if args.judge:
        judge_ctx = build_judge_ctx(base, args.judge_model)

    workers = args.concurrency or (4 if args.live else 1)
    report = {"created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "mode": "live" if args.live else "offline", "fingerprint": fingerprint(),
              "case_count": len(cases), "reps": args.reps, "judge_model": args.judge_model if args.judge else None,
              "configs": {}}
    for name, tiers in variants:
        cfg = router_config(base, tiers)
        jobs = [c for c in cases for _ in range(args.reps)]
        print(f"\n== {name}: {describe(cfg)['plan']} plans, {len(jobs)} runs", flush=True)

        def one(c: EvalCase, cfg=cfg) -> dict:
            r = run_case(c, cfg=cfg, settings=settings, live=args.live, render=args.render,
                         judge_ctx=judge_ctx, budget=budget)
            mark = "ok " if r.get("passed") else ("ERR" if r["status"] != "ok" else "NO ")
            print(f"  {mark} {c.name:44} ${r.get('cost_usd', 0):.4f} {r.get('latency_s', 0):>6}s "
                  f"chg={r.get('changes', '-')} fab={len(r.get('fabrications', []))} "
                  f"{','.join(r.get('failures', [])) or r.get('error', '')[:60]}", flush=True)
            return r

        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(one, jobs))
        report["configs"][name] = {"overrides": tiers, "models": describe(cfg), "summary": aggregate(rows),
                                   "results": rows}
    report["total_spend_usd"] = round(budget.spent, 6) if args.live else 0.0
    if args.live and budget.exhausted:
        print(f"\nBudget of ${args.max_usd:.2f} reached; remaining cases were skipped.")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or (REPORTS / stamp / "report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    safe_write.write_json(out, report, ensure_ascii=False)
    md = markdown(report)
    safe_write.write_text(out.with_suffix(".md"), md)
    print("\n" + safe_write.redact(md))
    print(f"Report: {out}")
    if args.save_summary:
        if not args.live:
            print("--save-summary is for live runs; skipped.")
        else:
            SUMMARY.parent.mkdir(parents=True, exist_ok=True)
            safe_write.write_json(SUMMARY, summary_record(report))
            print(f"Saved {SUMMARY.relative_to(ROOT)}. Commit it with the prompt or model change.")
    ok = all(r["status"] == "ok" and r["passed"] for cfgr in report["configs"].values() for r in cfgr["results"])
    return 0 if ok else 1


def summary_record(report: dict) -> dict:
    """The small, committable part of a live report: no resume text, just numbers."""
    return {"created_at": report["created_at"], "fingerprint": report["fingerprint"],
            "case_count": report["case_count"], "reps": report["reps"], "judge_model": report["judge_model"],
            "configs": {n: {"overrides": c["overrides"], "models": c["models"], "summary": c["summary"],
                            "failed_cases": sorted(r["case"] for r in c["results"]
                                                   if r["status"] != "ok" or not r["passed"])}
                        for n, c in report["configs"].items()}}


if __name__ == "__main__":
    raise SystemExit(main())
