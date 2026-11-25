"""A hash of everything that changes model behaviour: model routing and prices, every
prompt version, and the validation rules. Live reports record it so CI can tell whether
a committed live result still describes the code."""

from __future__ import annotations

import hashlib

from evalkit.cases import ROOT

INPUTS = ["config/models.yaml", "backend/roletailor/ai/prompts", "backend/roletailor/pipeline/validation"]


def behaviour_files() -> list[str]:
    files = []
    for rel in INPUTS:
        p = ROOT / rel
        if p.is_file():
            files.append(p)
        else:
            files += sorted(x for x in p.rglob("*") if x.is_file() and x.suffix in {".md", ".py", ".yaml"})
    return [str(f.relative_to(ROOT)) for f in files]


def fingerprint() -> str:
    h = hashlib.sha256()
    for rel in behaviour_files():
        h.update(rel.encode())
        h.update(b"\0")
        h.update((ROOT / rel).read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()[:16]
