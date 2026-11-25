"""Gold set: run the pipeline on real resume and job pairs, and calibrate the LLM judge
against human ratings. See evals/gold/README.md for the folder layout and workflow.

    python ../evals/run_gold.py run --yes [--case NAME ...] [--max-usd 2] [--judge-model M]
    python ../evals/run_gold.py calibrate [--case NAME ...] [--out PATH]

`run` calls paid APIs and needs ANTHROPIC_API_KEY (environment or .env). `calibrate` is
offline. Everything is written under evals/gold/<case>/output/ and evals/reports/, which
are not committed; resume text never goes anywhere else.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "evals")]

from evalkit import gold  # noqa: E402
from run_evals import Budget, build_judge_ctx, load_dotenv  # noqa: E402

from roletailor.ai.cache import MemoryCache  # noqa: E402
from roletailor.ai.gateway import AIUnavailable, build_gateway  # noqa: E402
from roletailor.ai.router import ModelRouter  # noqa: E402
from roletailor.ai.telemetry import MemorySink  # noqa: E402
from roletailor.config import Settings  # noqa: E402
from roletailor.documents import ParsedDocument, read_docx, read_pdf_text, read_plain_text  # noqa: E402
from roletailor.pipeline.orchestrator import TailoringPrefs, tailor  # noqa: E402

GOLD_DIR = ROOT / "evals" / "gold"
REPORTS = ROOT / "evals" / "reports"


# --------------------------------------------------------------------------- reading a case


def find_cases(gold_dir: Path, names: list[str] | None) -> list[Path]:
    """Case folders that have a resume and job.txt. Folders starting with _ (the example)
    are skipped unless named."""
    out = []
    for d in sorted(p for p in gold_dir.iterdir() if p.is_dir()):
        if (names and d.name not in names) or (not names and d.name.startswith("_")):
            continue
        out.append(d)
    return out


def resume_file(case: Path) -> Path | None:
    return next((p for p in (case / "resume.docx", case / "resume.pdf") if p.is_file()), None)


def parse_resume(path: Path) -> tuple[ParsedDocument, bytes | None]:
    """DOCX can be edited in place; PDF yields text only. Returns (document, docx bytes or None)."""
    data = path.read_bytes()
    if path.suffix == ".pdf":
        return read_pdf_text(data), None
    return read_docx(data), data


def human_paragraphs(case: Path) -> list[str] | None:
    """Text paragraphs of human_tailored.docx or .txt, or None when there is none."""
    docx, txt = case / "human_tailored.docx", case / "human_tailored.txt"
    if docx.is_file():
        return [b.text for b in read_docx(docx.read_bytes()).text_blocks()]
    if txt.is_file():
        return [b.text for b in read_plain_text(txt.read_text()).text_blocks()]
    return None


# --------------------------------------------------------------------------- output files


def review_markdown(case: str, changes: list[dict], gaps: list[str]) -> str:
    lines = [f"# {case}: what the tool changed", "", f"{len(changes)} change(s). "
             "Compare each pair, then fill in ratings.yaml.", ""]
    for c in changes:
        lines += [f"## {c['block_id']}", "", f"**Original:** {c['original']}", "",
                  f"**Proposed:** {c['proposed']}", "", f"*Why:* {c['reason']}", ""]
    lines += ["## Gaps reported (requirements the resume does not show)", ""]
    lines += [f"- {g}" for g in gaps] or ["- none"]
    return "\n".join(lines) + "\n"


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def run_one(case: Path, *, settings: Settings, base: dict, judge_ctx: dict, budget: Budget) -> dict:
    from evalkit.judge import judge

    rpath = resume_file(case)
    job_path = case / "job.txt"
    if rpath is None or not job_path.is_file():
        return {"case": case.name, "status": "error", "error": "needs resume.docx|pdf and job.txt"}
    if budget.exhausted:
        return {"case": case.name, "status": "skipped", "error": "budget exhausted"}
    job = job_path.read_text()
    doc, docx_bytes = parse_resume(rpath)
    original = {b.id: b.text for b in doc.text_blocks()}
    sink = MemorySink()
    gw = build_gateway(sink, settings=settings, router=ModelRouter(base), cache=MemoryCache())
    try:
        result = tailor(document=doc, job_text=job, gateway=gw, prefs=TailoringPrefs(),
                        source_docx=docx_bytes)
    except AIUnavailable as e:
        budget.add(sink.total_cost)
        return {"case": case.name, "status": "error", "error": f"AIUnavailable: {e}"}
    budget.add(sink.total_cost)

    out = case / "output"
    out.mkdir(exist_ok=True)
    changes = [{"block_id": c.block_path, "original": c.prior_text, "proposed": c.proposed_text,
                "reason": c.reason} for c in result.changes]
    digest = gold.changes_hash(changes)
    write_json(out / "changes.json", changes)
    (out / "review.md").write_text(review_markdown(case.name, changes, list(result.plan.gaps)))

    resume_text = "\n".join(original.values())
    edits = [{"before": c["original"], "after": c["proposed"]} for c in changes]
    judge_cost = 0.0
    verdict, jc = judge(judge_ctx["provider"], judge_ctx["spec"], job=job, resume_text=resume_text, edits=edits)
    budget.add(jc)
    judge_cost += jc
    write_json(out / "judge.json", {**verdict, "changes_hash": digest})

    human = human_paragraphs(case)
    if human is not None:
        h_edits = gold.align_paragraphs(list(original.values()), human)
        hv, jc = judge(judge_ctx["provider"], judge_ctx["spec"], job=job, resume_text=resume_text, edits=h_edits)
        budget.add(jc)
        judge_cost += jc
        write_json(out / "judge_human.json", {**hv, "edits_found": len(h_edits)})

    if not (case / "ratings.yaml").is_file():
        (out / "ratings.template.yaml").write_text(gold.ratings_template(changes, digest))
    cost = {"pipeline_usd": round(sink.total_cost, 6), "judge_usd": round(judge_cost, 6),
            "judge_model": judge_ctx["spec"].model}
    write_json(out / "cost.json", cost)
    return {"case": case.name, "status": "ok", "changes": len(changes), **cost}


# --------------------------------------------------------------------------- commands


def cmd_run(args: argparse.Namespace) -> int:
    if not args.yes:
        print("`run` calls paid APIs (about $0.05 per case with the judge). Re-run with --yes.")
        return 2
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Add it to .env at the repo root (never commit it) "
              "or export it, then re-run.")
        return 2
    cases = find_cases(GOLD_DIR, args.case)
    if not cases:
        print(f"No gold cases found in {GOLD_DIR}. See evals/gold/README.md.")
        return 2
    settings = Settings(llm_mode="live")
    base = yaml.safe_load(settings.models_config_path.read_text())
    judge_ctx = build_judge_ctx(base, args.judge_model)
    budget = Budget(args.max_usd)
    failed = 0
    for case in cases:
        try:
            row = run_one(case, settings=settings, base=base, judge_ctx=judge_ctx, budget=budget)
        except Exception as e:  # noqa: BLE001 - one bad case should not stop the others
            row = {"case": case.name, "status": "error", "error": f"{type(e).__name__}: {e}"[:200]}
        failed += row["status"] != "ok"
        print(f"  {row['status']:7} {case.name}  " + (
            f"{row['changes']} changes, ${row['pipeline_usd'] + row['judge_usd']:.4f}"
            if row["status"] == "ok" else row.get("error", "")))
    print(f"\nSpent ${budget.spent:.4f} of ${args.max_usd:.2f}. Next: read output/review.md in each case, "
          "copy output/ratings.template.yaml to ratings.yaml and fill it in, then `calibrate`.")
    return 1 if failed else 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    report = gold.calibrate(GOLD_DIR, only=args.case)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    md = gold.calibration_markdown(report, stamp)
    out = args.out or (REPORTS / f"gold_{stamp}" / "calibration.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    write_json(out.with_suffix(".json"), report)
    print(md)
    print(f"Report: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="tailor each gold case and judge it (live, paid)")
    r.add_argument("--case", action="append", help="only these case folders (repeatable)")
    r.add_argument("--max-usd", type=float, default=2.0, help="stop starting new work past this spend")
    r.add_argument("--judge-model", default="claude-sonnet", help="models.yaml key for the judge")
    r.add_argument("--yes", action="store_true", help="confirm live spending")
    r.set_defaults(fn=cmd_run)
    c = sub.add_parser("calibrate", help="compare judge scores with human ratings (offline)")
    c.add_argument("--case", action="append", help="only these case folders (repeatable)")
    c.add_argument("--out", type=Path, help="write the markdown report here (json beside it)")
    c.set_defaults(fn=cmd_calibrate)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
