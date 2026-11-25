"""Pure logic for the gold set: ratings schema, hashing, paragraph alignment, statistics,
and the judge calibration report. No network and no model calls, so it is unit-tested.

Layout of one gold case (evals/gold/<name>/): resume.docx|pdf, job.txt, optional
human_tailored.docx|txt, optional ratings.yaml, and output/ written by run_gold.py.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import statistics
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

DIMENSIONS = ("truthfulness", "relevance", "readability", "voice")
MIN_N_FOR_STATS = 5      # below this, correlation is not reported
MIN_CASES_TO_CONCLUDE = 10
MAX_ABS_BIAS = 0.5       # "calibrated" thresholds
MAX_MAD = 1.0


# --------------------------------------------------------------------------- ratings


class Scores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    truthfulness: int | None = Field(default=None, ge=1, le=5)
    relevance: int | None = Field(default=None, ge=1, le=5)
    readability: int | None = Field(default=None, ge=1, le=5)
    voice: int | None = Field(default=None, ge=1, le=5)


class Ratings(BaseModel):
    """What a human fills in for one case. Blank (null) scores are allowed and skipped."""

    model_config = ConfigDict(extra="forbid")
    changes_hash: str | None = None
    rater: str = ""
    notes: str = ""
    scores: Scores = Field(default_factory=Scores)
    accept: dict[str, bool | None] = Field(default_factory=dict)  # block id -> keep this change?
    missed_opportunities: list[str] = Field(default_factory=list)


def load_ratings(path: Path) -> Ratings:
    """Raises ValueError with a readable message when the file is malformed."""
    try:
        return Ratings.model_validate(yaml.safe_load(path.read_text()) or {})
    except (yaml.YAMLError, ValidationError) as e:
        raise ValueError(f"{path}: {e}") from e


def ratings_template(changes: list[dict], digest: str) -> str:
    """Text of ratings.template.yaml, with a per-change accept list and the output hash."""
    accept = "\n".join(f"  {c['block_id']}: null   # {c['proposed'][:70].replace(chr(10), ' ')!r}"
                       for c in changes) or "  {}"
    return f"""# Copy this file to ratings.yaml and fill it in. Leave anything you are unsure about as null.
# changes_hash ties these ratings to the exact output you read (output/review.md).
# If you re-run the tool, the hash changes and old ratings are ignored until you re-rate.
changes_hash: {digest}
rater: ""            # your name or initials
notes: ""            # anything the numbers do not capture

# Overall scores for the tool's output, 1 (bad) to 5 (excellent):
scores:
  truthfulness: null   # every claim is supported by the original resume; anything invented is 1
  relevance: null      # did the edits surface the honest matches to this job? 5 = the important ones
                       # are captured; 3 = about half; 1 = cosmetic edits or clear matches left out
  readability: null    # clear, specific, grammatical, no filler or AI-sounding phrases
  voice: null          # still sounds like the candidate; structure kept

# Per change, would you keep it? true or false. Key is the block id shown in review.md.
accept:
{accept}

# Honest matches between the resume and the job that the tool should have surfaced and did not.
missed_opportunities: []
"""


# --------------------------------------------------------------------------- hashing


def changes_hash(changes: list[dict]) -> str:
    """Stable short hash of changes.json content (block id, original, proposed, reason)."""
    canon = json.dumps(changes, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- alignment


def align_paragraphs(original: list[str], human: list[str], *, min_ratio: float = 0.4) -> list[dict]:
    """Edits a human made, as [{'before', 'after'}] pairs (the shape the judge takes).

    Paragraphs are aligned with difflib. Inside a replaced stretch, each original
    paragraph is paired with its most similar unused new paragraph if they share at
    least `min_ratio` similarity; anything else is a pure insertion or deletion and is
    not an edit of an existing block.
    """
    sm = difflib.SequenceMatcher(None, original, human, autojunk=False)
    edits: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "replace":
            continue
        used: set[int] = set()
        for i in range(i1, i2):
            best, best_r = None, 0.0
            for j in range(j1, j2):
                if j in used:
                    continue
                r = difflib.SequenceMatcher(None, original[i], human[j]).ratio()
                if r > best_r:
                    best, best_r = j, r
            if best is not None and best_r >= min_ratio:
                used.add(best)
                edits.append({"before": original[i], "after": human[best]})
    return edits


# --------------------------------------------------------------------------- statistics


def mean(xs: list[float]) -> float | None:
    return round(statistics.fmean(xs), 3) if xs else None


def bias(judge: list[float], human: list[float]) -> float | None:
    """Judge minus human, averaged. Negative means the judge is harsher."""
    return round(statistics.fmean(j - h for j, h in zip(judge, human, strict=True)), 3) if judge else None


def mean_abs_diff(judge: list[float], human: list[float]) -> float | None:
    return round(statistics.fmean(abs(j - h) for j, h in zip(judge, human, strict=True)), 3) if judge else None


def share_within(judge: list[float], human: list[float], tol: float = 1.0) -> float | None:
    if not judge:
        return None
    return round(sum(abs(j - h) <= tol for j, h in zip(judge, human, strict=True)) / len(judge), 3)


def _ranks(xs: list[float]) -> list[float]:
    """1-based ranks; tied values share the average of their positions."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float | None:
    """Spearman rank correlation, None when n < 5 or either side has no variance."""
    if len(a) != len(b):
        raise ValueError("length mismatch")
    if len(a) < MIN_N_FOR_STATS:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va == 0 or vb == 0:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    return round(cov / math.sqrt(va * vb), 3)


def dimension_stats(judge: list[float], human: list[float]) -> dict:
    return {"n": len(judge), "human_mean": mean(human), "judge_mean": mean(judge),
            "bias": bias(judge, human), "mad": mean_abs_diff(judge, human),
            "within_1": share_within(judge, human), "spearman": spearman(judge, human)}


def verdict(dim: str, s: dict) -> str:
    """One plain sentence per dimension."""
    if s["n"] < MIN_N_FOR_STATS:
        return f"{dim}: only {s['n']} paired scores; not enough to judge."
    b, mad = s["bias"], s["mad"]
    if abs(b) <= MAX_ABS_BIAS and mad <= MAX_MAD:
        return f"{dim}: calibrated (bias {b:+.2f}, mean abs diff {mad:.2f}); judge scores can be trusted."
    if abs(b) > MAX_ABS_BIAS:
        word = "harsher" if b < 0 else "more generous"
        return f"{dim}: judge is {abs(b):.1f} points {word} than human raters; treat as directional."
    return f"{dim}: no consistent bias but individual scores differ by {mad:.1f} on average; treat as directional."


# --------------------------------------------------------------------------- calibration


def read_json(path: Path):
    return json.loads(path.read_text())


def calibrate(gold_dir: Path, *, only: list[str] | None = None) -> dict:
    """Compare judge.json with ratings.yaml across cases. Offline."""
    pairs: dict[str, tuple[list[float], list[float]]] = {d: ([], []) for d in DIMENSIONS}
    used, skipped, warnings = [], [], []
    accepts: list[bool] = []
    judge_tool: dict[str, list[float]] = {d: [] for d in DIMENSIONS}
    judge_human: dict[str, list[float]] = {d: [] for d in DIMENSIONS}
    n_judge_human = 0

    for case in sorted(p for p in gold_dir.iterdir() if p.is_dir()):
        if (only and case.name not in only) or (not only and case.name.startswith("_")):
            continue
        out = case / "output"
        ratings_path = case / "ratings.yaml"
        if not ratings_path.is_file():
            continue
        if not (out / "judge.json").is_file() or not (out / "changes.json").is_file():
            skipped.append(case.name)
            warnings.append(f"{case.name}: ratings.yaml exists but there is no judge output; run it first.")
            continue
        try:
            ratings = load_ratings(ratings_path)
        except ValueError as e:
            skipped.append(case.name)
            warnings.append(f"{case.name}: invalid ratings.yaml, skipped ({e})")
            continue
        changes = read_json(out / "changes.json")
        judge_data = read_json(out / "judge.json")
        current = changes_hash(changes)
        if ratings.changes_hash != current or judge_data.get("changes_hash", current) != current:
            skipped.append(case.name)
            warnings.append(f"{case.name}: stale, ratings were made for a different output; "
                            f"copy the new ratings.template.yaml and re-rate.")
            continue
        given = {d: getattr(ratings.scores, d) for d in DIMENSIONS if getattr(ratings.scores, d) is not None}
        if not given:
            skipped.append(case.name)
            warnings.append(f"{case.name}: ratings.yaml has no scores filled in, skipped.")
            continue
        used.append(case.name)
        for d, h in given.items():
            pairs[d][0].append(float(judge_data[d]))
            pairs[d][1].append(float(h))
        known = {c["block_id"] for c in changes}
        accepts += [v for k, v in ratings.accept.items() if k in known and v is not None]
        jh = out / "judge_human.json"
        if jh.is_file():
            hv = read_json(jh)
            n_judge_human += 1
            for d in DIMENSIONS:
                judge_tool[d].append(float(judge_data[d]))
                judge_human[d].append(float(hv[d]))

    dims = {d: dimension_stats(*pairs[d]) for d in DIMENSIONS}
    report = {
        "cases_used": used, "cases_skipped": skipped, "warnings": warnings,
        "n_cases": len(used), "enough_cases": len(used) >= MIN_CASES_TO_CONCLUDE,
        "dimensions": dims,
        "human_accept_rate": round(sum(accepts) / len(accepts), 3) if accepts else None,
        "human_accept_n": len(accepts),
        "human_tailored": {"n": n_judge_human,
                           "judge_on_tool": {d: mean(judge_tool[d]) for d in DIMENSIONS},
                           "judge_on_human": {d: mean(judge_human[d]) for d in DIMENSIONS}},
        "verdicts": [verdict(d, dims[d]) for d in DIMENSIONS],
    }
    return report


def _fmt(x) -> str:
    return "n/a" if x is None else (f"{x:.2f}" if isinstance(x, float) else str(x))


def calibration_markdown(r: dict, stamp: str = "") -> str:
    lines = [f"# Judge calibration {stamp}".rstrip(), "",
             f"Cases compared: {r['n_cases']} ({', '.join(r['cases_used']) or 'none'}).", ""]
    for w in r["warnings"]:
        lines.append(f"- WARNING {w}")
    if r["warnings"]:
        lines.append("")
    if not r["enough_cases"]:
        lines += [f"**Only {r['n_cases']} rated cases (need at least {MIN_CASES_TO_CONCLUDE}). "
                  "Nothing below is conclusive; treat every number as anecdotal.**", ""]
    lines += ["| dimension | n | human mean | judge mean | bias (judge-human) | mean abs diff | within 1 | Spearman |",
              "|---|---|---|---|---|---|---|---|"]
    for d, s in r["dimensions"].items():
        lines.append(f"| {d} | {s['n']} | {_fmt(s['human_mean'])} | {_fmt(s['judge_mean'])} | {_fmt(s['bias'])} | "
                     f"{_fmt(s['mad'])} | {_fmt(s['within_1'])} | {_fmt(s['spearman'])} |")
    lines += ["", "Negative bias means the judge is harsher than the human raters.", ""]
    lines.append(f"Human accept rate for the tool's changes: {_fmt(r['human_accept_rate'])} "
                 f"({r['human_accept_n']} changes rated).")
    ht = r["human_tailored"]
    if ht["n"]:
        lines += ["", f"Judge scores on human-tailored versions vs the tool ({ht['n']} cases). If careful human "
                      "work scores low, the scale is too harsh.", "",
                  "| dimension | judge on tool | judge on human |", "|---|---|---|"]
        lines += [f"| {d} | {_fmt(ht['judge_on_tool'][d])} | {_fmt(ht['judge_on_human'][d])} |"
                  for d in DIMENSIONS]
    lines += ["", "## Verdict", ""] + [f"- {v}" for v in r["verdicts"]]
    return "\n".join(lines) + "\n"
