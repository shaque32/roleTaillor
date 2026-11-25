"""Check every eval case before it is trusted: schema, canaries, and that the resume
renders and parses into the sections the pipeline needs.

    cd backend && .venv/bin/python ../evals/validate_cases.py [case_name ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "evals")]

from evalkit.cases import EvalCase, load_cases  # noqa: E402

from roletailor.documents import read_docx  # noqa: E402
from roletailor.pipeline import heuristics, lexicon, stages  # noqa: E402
from roletailor.pipeline.text import contains_term  # noqa: E402


def _related_forms(term: str) -> list[str]:
    """The term plus lexicon synonyms in either direction (AWS <-> Amazon Web Services)."""
    forms = [term, *lexicon.SYNONYMS.get(term, [])]
    for canonical, syns in lexicon.SYNONYMS.items():
        if any(s.lower() == term.lower() for s in syns):
            forms += [canonical, *syns]
    return forms


def problems(case: EvalCase) -> list[str]:
    out: list[str] = []
    doc = read_docx(case.resume_bytes())
    resume_text = "\n".join(b.text for b in doc.blocks)
    for c in case.canaries:
        if not contains_term(case.job, c):
            out.append(f"canary '{c}' does not appear in the job text")
        hit = next((f for f in _related_forms(c) if contains_term(resume_text, f)), None)
        if hit:
            out.append(f"canary '{c}' is evidenced in the resume (as '{hit}')")
    if len(set(map(str.lower, case.canaries))) != len(case.canaries):
        out.append("duplicate canaries")
    for g in case.expect.live_expected_gaps:
        if g not in case.canaries:
            out.append(f"live_expected_gaps term '{g}' is not a canary")
    structure = heuristics.structure_from_blocks(doc.blocks)
    kinds = {s.kind for s in structure.sections}
    if "experience" not in kinds:
        out.append(f"no experience section detected (found {sorted(kinds)})")
    scopes = stages.block_scopes(structure, doc)
    if sum(s == "bullet" for s in scopes.values()) < 1:
        out.append("no editable experience bullets detected")
    if not isinstance(case.resume, str):
        if "@example." not in case.resume.contact:
            out.append("contact email must use an example.com / example.org address")
        if len(case.job.strip()) < 40:
            out.append("job text is too short to be a job description")
    return out


def main(argv: list[str]) -> int:
    cases = load_cases(names=argv or None)
    bad = 0
    for c in cases:
        ps = problems(c)
        bad += bool(ps)
        for p in ps:
            print(f"FAIL {c.name}: {p}")
    print(f"{len(cases)} cases checked, {bad} with problems")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
