"""Guided resume creation: turn the form into Blocks and render them to DOCX."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from roletailor.documents.model import Block
from roletailor.domain.models import Contact, SectionKind


class GuidedContact(Contact):
    full_name: str = Field(min_length=1, max_length=200)


class _Item(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ExperienceItem(_Item):
    company: str = ""
    title: str = ""
    location: str | None = None
    start: str | None = None
    end: str | None = None
    bullets: list[str] = Field(default_factory=list, max_length=40)


class EducationItem(_Item):
    institution: str = ""
    degree: str | None = None
    field: str | None = None
    start: str | None = None
    end: str | None = None
    details: str | None = None


class CertificationItem(_Item):
    name: str = ""
    issuer: str | None = None
    date: str | None = None


class ProjectItem(_Item):
    name: str = ""
    link: str | None = None
    description: str | None = None
    bullets: list[str] = Field(default_factory=list, max_length=40)


class TextItem(_Item):
    text: str = ""


ITEM_MODELS: dict[str, type[_Item]] = {
    "experience": ExperienceItem, "education": EducationItem,
    "certifications": CertificationItem, "projects": ProjectItem,
}


class GuidedSection(BaseModel):
    kind: SectionKind
    title: str = Field(max_length=200)
    items: list[_Item] = Field(default_factory=list, max_length=60)

    @model_validator(mode="before")
    @classmethod
    def _typed_items(cls, data: Any) -> Any:
        if isinstance(data, dict):
            model = ITEM_MODELS.get(data.get("kind", ""), TextItem)
            data = {**data, "items": [
                model.model_validate({"text": i} if isinstance(i, str) else i)
                for i in data.get("items") or []
            ]}
        return data


class GuidedResume(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    contact: GuidedContact
    sections: list[GuidedSection] = Field(min_length=1, max_length=20)


def _join(parts: tuple[str | None, ...], sep: str) -> str:
    return sep.join(p.strip() for p in parts if p and p.strip())


def _dated(head: str, *dates: str | None) -> str:
    """Dates after a tab are right-aligned by the renderer."""
    when = _join(dates, " - ")
    return f"{head}\t{when}" if when else head


def _item_lines(item: _Item) -> tuple[str, list[str], list[str]]:
    """(entry line, plain paragraphs, bullets) for one item."""
    match item:
        case ExperienceItem():
            head = _join((item.title, item.company, item.location), ", ")
            return _dated(head, item.start, item.end), [], item.bullets
        case EducationItem():
            degree = _join((item.degree, item.field), " in ")
            return _dated(_join((degree, item.institution), ", "), item.start, item.end), \
                [item.details or ""], []
        case CertificationItem():
            return _dated(_join((item.name, item.issuer), ", "), item.date), [], []
        case ProjectItem():
            return _join((item.name, item.link), " | "), [item.description or ""], item.bullets
        case TextItem():
            return "", [item.text], []
    raise TypeError(type(item))


def build_blocks(form: GuidedResume) -> tuple[list[Block], list[dict]]:
    """Blocks with ids g0, g1, ... plus `Section`-shaped metadata for the renderer:
    [{"kind", "title", "heading_block_id", "block_ids"}]."""
    blocks: list[Block] = []

    def add(text: str, **kwargs) -> str:
        block = Block(id=f"g{len(blocks)}", text=text.strip(), **kwargs)
        blocks.append(block)
        return block.id

    contact = form.contact
    # Blocks no section references form the renderer's header (name, contact line).
    add(contact.full_name)
    if contact_line := _join((contact.email, contact.phone, contact.location, *contact.links), " | "):
        add(contact_line)
    sections_meta: list[dict] = []

    for section in form.sections:
        heading_id = add(section.title, style_name="Heading 1", is_heading=True)
        block_ids: list[str] = []
        for item in section.items:
            entry, paragraphs, bullets = _item_lines(item)
            if entry.strip():
                block_ids.append(add(entry, style_name="Heading 2", run_styles=[]))
            block_ids.extend(add(t) for t in paragraphs if t.strip())
            block_ids.extend(
                add(b, style_name="List Bullet", is_list_item=True) for b in bullets if b.strip()
            )
        sections_meta.append({
            "kind": section.kind, "title": section.title,
            "heading_block_id": heading_id, "block_ids": block_ids,
        })
    return blocks, sections_meta


def render(form: GuidedResume) -> bytes:
    from roletailor.documents import render_structured_docx

    blocks, sections_meta = build_blocks(form)
    return render_structured_docx(blocks, sections_meta)
