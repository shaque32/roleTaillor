"""Deterministic analysis used three ways:

1. evidence matching before planning (which blocks already mention each JD keyword);
2. graceful degradation when every model for a cacheable stage is down;
3. the offline fake provider for tests, local dev, and CI evals.
"""

from __future__ import annotations

import re

from roletailor.documents.model import Block
from roletailor.domain.models import (
    Contact,
    ExperienceEntry,
    FactInventory,
    JobAnalysis,
    Keyword,
    ResumeStructure,
    Section,
)
from roletailor.pipeline import lexicon
from roletailor.pipeline.text import clean, contains_term, norm, numbers, tech_terms

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_URL = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com|github\.com)/[\w/.-]+", re.I)
_DATE = re.compile(
    r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+)?(19|20)\d{2}"
    r"|present|current", re.I)


def _heading_kind(text: str) -> str | None:
    t = norm(text).rstrip(":")
    for kind, names in lexicon.SECTION_HEADINGS.items():
        if t in names:
            return kind
    return None


def structure_from_blocks(blocks: list[Block]) -> ResumeStructure:
    """Section a resume by heading text, and build a conservative fact inventory."""
    text_blocks = [b for b in blocks if b.text.strip()]
    contact = Contact()
    sections: list[Section] = []
    current = Section(kind="header", title="Header")
    for b in text_blocks:
        kind = _heading_kind(b.text) if (b.is_heading or len(b.text) < 40) else None
        if kind:
            sections.append(current)
            current = Section(kind=kind, title=clean(b.text), heading_block_id=b.id,
                              block_ids=[b.id])
            continue
        current.block_ids.append(b.id)
    sections.append(current)
    sections = [s for s in sections if s.block_ids]

    by_id = {b.id: b for b in text_blocks}
    header = next((s for s in sections if s.kind == "header"), None)
    if header:
        head_text = " | ".join(by_id[i].text for i in header.block_ids)
        contact.full_name = clean(by_id[header.block_ids[0]].text) if header.block_ids else None
        contact.email = (m.group(0) if (m := _EMAIL.search(head_text)) else None)
        contact.phone = (m.group(0) if (m := _PHONE.search(head_text)) else None)
        contact.links = _URL.findall(head_text)

    for s in sections:
        if s.kind == "experience":
            s.entries = _entries(s, by_id)

    return ResumeStructure(contact=contact, sections=sections, facts=_facts(text_blocks, sections, by_id))


def _entries(section: Section, by_id: dict[str, Block]) -> list[ExperienceEntry]:
    entries: list[ExperienceEntry] = []
    for bid in section.block_ids[1:] if section.heading_block_id else section.block_ids:
        b = by_id[bid]
        is_header_line = not b.is_list_item and (_DATE.search(b.text) or len(b.text) < 70)
        if is_header_line and (not entries or entries[-1].bullet_block_ids):
            parts = [p.strip() for p in re.split(r"\s[|,–—-]\s|\t+", b.text) if p.strip()]
            entries.append(ExperienceEntry(company=parts[0] if parts else clean(b.text),
                                           title=parts[1] if len(parts) > 1 else "",
                                           header_block_ids=[bid]))
        elif is_header_line and entries:
            entries[-1].header_block_ids.append(bid)
            if not entries[-1].title:
                entries[-1].title = clean(b.text)
        elif entries:
            entries[-1].bullet_block_ids.append(bid)
        else:
            entries.append(ExperienceEntry(company="", title="", bullet_block_ids=[bid]))
    return entries


def _facts(blocks: list[Block], sections: list[Section], by_id: dict[str, Block]) -> FactInventory:
    all_text = "\n".join(b.text for b in blocks)
    facts = FactInventory()
    facts.tools = sorted({t for t in lexicon.TOOLS if contains_term(all_text, t)}
                         | {t for t in tech_terms(all_text) if len(t) <= 30})
    facts.skills = sorted(s for s in lexicon.SKILLS if contains_term(all_text, s))
    facts.metrics = sorted(numbers(all_text))
    for s in sections:
        for e in s.entries:
            if e.company:
                facts.companies.append(e.company)
            if e.title:
                facts.titles.append(e.title)
        if s.kind == "certifications":
            facts.certifications += [clean(by_id[i].text) for i in s.block_ids if i != s.heading_block_id]
        if s.kind == "education":
            facts.degrees += [clean(by_id[i].text) for i in s.block_ids if i != s.heading_block_id]
    return facts


def job_from_text(job_text: str) -> JobAnalysis:
    """Lexicon-based JD analysis. Coarser than the model, but never invents terms."""
    text = clean(job_text)
    lines = [ln.strip(" -•*\t") for ln in job_text.splitlines() if ln.strip()]
    title = lines[0][:120] if lines else None
    required_zone = norm(text)
    keywords: list[Keyword] = []
    for term, category in [(t, "tool") for t in lexicon.TOOLS] + [(s, "skill") for s in lexicon.SKILLS]:
        syns = lexicon.SYNONYMS.get(term, [])
        hits = sum(1 for x in [term, *syns] if contains_term(text, x))
        if not hits:
            continue
        n = norm(term)
        pos = required_zone.find(n)
        window = required_zone[max(0, pos - 300):pos] if pos >= 0 else ""
        must = re.search(r"(required|must|minimum|qualifications)", window)
        importance = "must" if must or required_zone.count(n) > 1 else "should"
        keywords.append(Keyword(term=term, importance=importance, category=category, synonyms=syns))
    resp = [ln for ln in lines[1:] if 25 < len(ln) < 200][:10]
    return JobAnalysis(title=title, responsibilities=resp, keywords=keywords[:35])


def keyword_evidence(job: JobAnalysis, blocks: list[Block]) -> dict[str, list[str]]:
    """JD keyword -> ids of blocks whose text mentions it or one of its synonyms."""
    return {
        k.term: [b.id for b in blocks if any(contains_term(b.text, x) for x in [k.term, *k.synonyms])]
        for k in job.keywords
    }
