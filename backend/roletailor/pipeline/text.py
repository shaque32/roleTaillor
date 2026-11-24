"""Deterministic text utilities used by matching, validation, and scoring."""

from __future__ import annotations

import re
import unicodedata

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—−"), "-")
_QUOTES = {ord("‘"): "'", ord("’"): "'", ord("“"): '"', ord("”"): '"'}

# Numbers with optional currency, magnitude, and percent: "$2.1M", "38%", "1,200", "3x".
_NUMBER_RE = re.compile(
    r"(?<![\w.])([$€£]?\s?\d[\d,]*(?:\.\d+)?)\s?(%|[kKmMbB](?:n|illion)?\b|x\b|\+)?"
)
# Tech-looking tokens: acronyms, CamelCase, or tokens with digits or + # . inside.
_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#./-]*[A-Za-z0-9+#]|[A-Za-z]")


def clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_DASHES).translate(_QUOTES)
    return re.sub(r"\s+", " ", text).strip()


def norm(text: str) -> str:
    """Lowercase form for matching. Keeps characters that matter in tech names."""
    t = clean(text).lower()
    t = re.sub(r"[^\w+#./\- ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def contains_term(text: str, term: str) -> bool:
    """Whole-term match that respects tokens like C++, C#, Node.js, and A/B."""
    t, n = norm(text), norm(term)
    if not n:
        return False
    return re.search(rf"(?<![\w+#]){re.escape(n)}(?![\w+#])", t) is not None


def contains_any(text: str, terms: list[str]) -> bool:
    return any(contains_term(text, x) for x in terms if x)


def count_term(text: str, term: str) -> int:
    n = norm(term)
    if not n:
        return 0
    return len(re.findall(rf"(?<![\w+#]){re.escape(n)}(?![\w+#])", norm(text)))


def numbers(text: str) -> set[str]:
    """Canonical numeric claims in the text, e.g. {"38%", "$2.1m", "12"}."""
    out = set()
    for m in _NUMBER_RE.finditer(clean(text)):
        value = m.group(1).replace(" ", "").replace(",", "")
        unit = (m.group(2) or "").lower()
        unit = {"million": "m", "mn": "m", "billion": "b", "bn": "b"}.get(unit, unit)
        out.add(value.lower() + unit)
    return out


def bare_numbers(text: str) -> set[str]:
    return {re.sub(r"[^\d.]", "", n).rstrip(".") for n in numbers(text)}


def tech_terms(text: str) -> set[str]:
    """Tokens that look like proper nouns or technologies, excluding sentence starts.

    Used to catch invented tools or names in rewrites: "Snowflake", "dbt", "AWS",
    "PySpark", "GPT-4". Ordinary lowercase words are ignored.
    """
    out = set()
    for sentence in re.split(r"(?<=[.;:!?])\s+|\s[-•]\s", clean(text)):
        tokens = list(_TERM_RE.finditer(sentence))
        for i, m in enumerate(tokens):
            tok = m.group(0).strip(".-/")
            if len(tok) < 2:
                continue
            first = i == 0
            has_upper_inside = any(c.isupper() for c in tok[1:])
            has_special = any(c in "+#" for c in tok) or any(c.isdigit() for c in tok)
            capitalized = tok[0].isupper()
            if has_upper_inside or has_special or (capitalized and not first):
                out.add(tok)
    return out


def first_word(text: str) -> str:
    m = re.match(r"\W*([A-Za-z]+)", clean(text))
    return m.group(1).lower() if m else ""
