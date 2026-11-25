"""Public posting APIs for the big applicant tracking systems.

A pasted job URL from Greenhouse, Lever, Ashby or SmartRecruiters maps to a JSON API
call, which is far more reliable than scraping the (often JavaScript-rendered) page.
This module only recognises URLs and normalises payloads. It makes no network calls:
`job_fetch` owns the HTTP client so every request goes through the same SSRF guards.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.%-]*")
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_BLOCK_TAGS = ("p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section")

_GREENHOUSE_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}
_LEVER_API = {"jobs.lever.co": "api.lever.co", "jobs.eu.lever.co": "api.eu.lever.co"}


class BoardParseError(Exception):
    """The API answered, but not with a posting we can use."""


@dataclass(frozen=True)
class BoardJob:
    text: str
    title: str | None
    company: str | None


@dataclass(frozen=True)
class BoardRequest:
    board: str
    api_url: str
    parse: Callable[[object], BoardJob]
    # Ashby's API only returns a whole board (often several MB), while its posting page
    # carries the job as JSON-LD in under 100 KB, so the page is tried first there.
    page_first: bool = False


def html_to_text(markup: object) -> str:
    """Flatten posting HTML to plain text, keeping paragraph and bullet boundaries."""
    if not isinstance(markup, str) or not markup:
        return ""
    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup(("script", "style")):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for item in soup.find_all("li"):
        # Editors often wrap the bullet text in a paragraph; unwrap it so the marker stays on its line.
        while True:
            first = next((c for c in item.children if not (isinstance(c, NavigableString) and not c.strip())), None)
            if not isinstance(first, Tag) or first.name not in ("p", "div"):
                break
            first.unwrap()
        item.insert(0, "- ")
    for cell in soup.find_all(("td", "th")):
        cell.append(" ")  # keep adjacent table cells from running together
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.append("\n")
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in soup.get_text("").splitlines())
    return "\n".join(line for line in lines if line and line != "-")


def _text(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _join(parts: list[str | None]) -> str:
    return "\n\n".join(part for part in parts if part)


def _section(heading: object, markup: object) -> str | None:
    body = html_to_text(markup)
    return "\n".join(part for part in (_text(heading), body) if part) if body else None


def _require_dict(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise BoardParseError("unexpected API response")
    return payload


def _parse_greenhouse(payload: object) -> BoardJob:
    data = _require_dict(payload)
    # Greenhouse returns the description as entity-escaped HTML.
    content = data.get("content")
    if not isinstance(content, str):
        raise BoardParseError("posting has no description")
    text = html_to_text(html.unescape(content))
    return BoardJob(text=text, title=_text(data.get("title")), company=_text(data.get("company_name")))


def _parse_lever(payload: object) -> BoardJob:
    data = _require_dict(payload)
    # descriptionPlain already holds the opening and the body.
    parts = [_text(data.get("descriptionPlain")) or html_to_text(data.get("description"))]
    lists = data.get("lists")
    for section in lists if isinstance(lists, list) else []:
        if isinstance(section, dict):
            parts.append(_section(section.get("text"), section.get("content")))
    parts.append(_text(data.get("additionalPlain")) or html_to_text(data.get("additional")))
    return BoardJob(text=_join(parts), title=_text(data.get("text")), company=None)


def _parse_ashby(job_id: str) -> Callable[[object], BoardJob]:
    def parse(payload: object) -> BoardJob:
        jobs = _require_dict(payload).get("jobs")
        for job in jobs if isinstance(jobs, list) else []:
            if isinstance(job, dict) and str(job.get("id", "")).lower() == job_id:
                text = html_to_text(job.get("descriptionHtml")) or (_text(job.get("descriptionPlain")) or "")
                return BoardJob(text=text, title=_text(job.get("title")), company=None)
        raise BoardParseError("posting not found on the Ashby job board")

    return parse


def _parse_smartrecruiters(payload: object) -> BoardJob:
    data = _require_dict(payload)
    job_ad = data.get("jobAd")
    sections = job_ad.get("sections") if isinstance(job_ad, dict) else None
    parts: list[str | None] = []
    for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
        section = sections.get(key) if isinstance(sections, dict) else None
        if isinstance(section, dict):
            parts.append(_section(section.get("title"), section.get("text")))
    company = data.get("company")
    return BoardJob(
        text=_join(parts),
        title=_text(data.get("name")),
        company=_text(company.get("name")) if isinstance(company, dict) else None,
    )


def _slug(value: str) -> str | None:
    return quote(value, safe="%") if _SLUG.fullmatch(value) else None


def match(url: str) -> BoardRequest | None:
    """Return the API request for a recognised job board URL, or None."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower().removeprefix("www.")
    segments = [segment for segment in parts.path.split("/") if segment]

    if host in _GREENHOUSE_HOSTS:
        board = job_id = None
        if len(segments) >= 3 and segments[1] == "jobs":
            board, job_id = segments[0], segments[2]
        elif segments[:2] == ["embed", "job_app"]:
            query = parse_qs(parts.query)
            board, job_id = query.get("for", [None])[0], query.get("token", [None])[0]
        board = _slug(board) if board else None
        if board and job_id and job_id.isascii() and job_id.isdigit():
            return BoardRequest(
                "greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}", _parse_greenhouse
            )
        return None

    if host in _LEVER_API:
        company = _slug(segments[0]) if segments else None
        if company and len(segments) >= 2 and _UUID.fullmatch(segments[1]):
            return BoardRequest(
                "lever", f"https://{_LEVER_API[host]}/v0/postings/{company}/{segments[1].lower()}", _parse_lever
            )
        return None

    if host == "jobs.ashbyhq.com":
        org = _slug(segments[0]) if segments else None
        if org and len(segments) >= 2 and _UUID.fullmatch(segments[1]):
            return BoardRequest(
                "ashby", f"https://api.ashbyhq.com/posting-api/job-board/{org}", _parse_ashby(segments[1].lower()),
                page_first=True,
            )
        return None

    if host == "jobs.smartrecruiters.com":
        company = _slug(segments[0]) if segments else None
        posting = re.match(r"\d+", segments[1]) if len(segments) >= 2 else None
        if company and posting:
            return BoardRequest(
                "smartrecruiters",
                f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting.group()}",
                _parse_smartrecruiters,
            )
        return None

    return None
