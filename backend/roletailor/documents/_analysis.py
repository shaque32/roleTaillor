"""Format-independent resume heuristics shared by the DOCX and PDF readers."""

from __future__ import annotations

import re

from .model import Block

# Section vocabulary, keyed by the kinds the structure stage cares about most.
SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "summary": ("summary", "profile", "objective", "about me", "overview"),
    "experience": ("experience", "employment", "work history", "career history"),
    "education": ("education", "academic"),
    "skills": ("skills", "competencies", "technologies", "tech stack", "expertise"),
    "certifications": ("certifications", "certificates", "licenses", "credentials"),
    "projects": ("projects",),
    "other": ("publications", "awards", "achievements", "honors", "volunteer", "interests",
              "languages", "references", "training", "courses", "leadership", "activities",
              "research", "patents", "affiliations"),
}
REQUIRED_SECTIONS = ("experience", "education", "skills")
_EXACT_TITLES = frozenset(alias for aliases in SECTION_ALIASES.values() for alias in aliases)

MAX_HEADING_CHARS = 40
MAX_HEADING_WORDS = 5
# Fewer capital letters than this is likely an acronym ("SQL", "AWS"), not a header.
MIN_CAPS_LETTERS = 4
BULLET_CHARS = "•●▪■◦○‣∙·–-*"
# Private-use glyphs emitted for Symbol/Wingdings bullets.
BULLET_CHARS += "\uf0b7\uf0a7"
_BULLET_PREFIX = re.compile(rf"^\s*[{re.escape(BULLET_CHARS)}]\s+")
_NON_WORD = re.compile(r"[^a-z& ]+")


def _normalize(text: str) -> str:
    return " ".join(_NON_WORD.sub(" ", text.lower()).split())


def section_kind(text: str) -> str | None:
    """Section kind a short heading-like line names, if any."""
    norm = _normalize(text)
    if not norm or len(norm.split()) > MAX_HEADING_WORDS:
        return None
    for kind, aliases in SECTION_ALIASES.items():
        if any(alias in norm for alias in aliases):
            return kind
    return None


def is_short_line(text: str) -> bool:
    t = text.strip()
    return (
        bool(t)
        and len(t) <= MAX_HEADING_CHARS
        and len(t.split()) <= MAX_HEADING_WORDS
        and "\t" not in t
        and not t.endswith((".", ","))
    )


def is_all_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= MIN_CAPS_LETTERS and all(c.isupper() for c in letters)


def looks_like_heading(text: str, *, all_bold: bool, allow_caps_only: bool = True) -> bool:
    """Heuristic resume section header: a short line that is all caps, or bold/standalone
    and named like a resume section. `allow_caps_only=False` is used for the first line of
    a document, where an all-caps line is usually the candidate's name."""
    if not is_short_line(text):
        return False
    kind = section_kind(text)
    if is_all_caps(text) and (allow_caps_only or kind):
        return True
    if kind is None:
        return False
    return all_bold or _normalize(text) in _EXACT_TITLES


def strip_bullet(text: str) -> tuple[str, bool]:
    """Remove a manual bullet glyph prefix; returns (text, had_bullet)."""
    match = _BULLET_PREFIX.match(text)
    return (text[match.end():], True) if match else (text, False)


def missing_section_findings(blocks: list[Block]) -> list[dict]:
    found = {section_kind(b.text) for b in blocks if b.is_heading}
    return [
        {"code": "missing_section", "detail": f"No {kind} section found"}
        for kind in REQUIRED_SECTIONS
        if kind not in found
    ]
