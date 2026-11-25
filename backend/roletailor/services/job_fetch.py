"""Fetch a job posting URL safely and extract its main text.

URLs from Greenhouse, Lever, Ashby and SmartRecruiters go to the board's public posting
API first (see `job_boards`); anything else, or a failed API call, uses the generic
page fetch. Both paths share one download function, so the guards below cover both.

SSRF guards: only http/https, every hop's host must resolve exclusively to public
addresses, redirects are followed manually (and re-checked), proxies from the
environment are ignored, responses are size-capped and time-limited (per read, and in
total by a deadline that cancels the fetch), and only ports 80 and 443 are allowed. Each connection is made to the exact
address that was checked, so a host cannot pass the check with a public address and
then answer the real lookup with a private one (DNS rebinding).
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from roletailor.services import job_boards

log = logging.getLogger(__name__)

MAX_REDIRECTS = 4
MIN_TEXT_CHARS = 200
_NOISE_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg")


class JobFetchError(Exception):
    pass


@dataclass(frozen=True)
class FetchedJob:
    text: str
    title: str | None
    company: str | None


def _resolve(host: str, port: int) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]


ALLOWED_PORTS = frozenset({80, 443})
MAX_ADDRESSES_TRIED = 3
# Lookups block, so they run on their own small pool where the deadline can abandon them.
_DNS_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="job-fetch-dns")


@dataclass(frozen=True)
class _Hop:
    """One validated hop: `host` is the ASCII (IDNA) name, `addresses` the vetted public
    IPs the connection may be made to, in resolver order."""

    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


def _check_url(url: str) -> _Hop:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise JobFetchError("only http and https URLs are supported")
    if parts.username is not None or parts.password is not None:
        raise JobFetchError("URLs with credentials are not supported")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise JobFetchError("invalid port") from exc
    if port not in ALLOWED_PORTS:
        raise JobFetchError("only ports 80 and 443 are supported")
    try:
        # The IDNA form is what goes on the wire (Host header, SNI); headers are ASCII only.
        host = httpx.URL(url).raw_host.decode("ascii")
    except (httpx.InvalidURL, UnicodeError) as exc:
        raise JobFetchError("invalid host name") from exc
    try:
        addresses = _resolve(host, port)
    except (socket.gaierror, UnicodeError) as exc:
        raise JobFetchError("host does not resolve") from exc
    if not addresses:
        raise JobFetchError("host does not resolve")
    vetted: list[str] = []
    for address in addresses:
        address = address.split("%", 1)[0]
        ip = ipaddress.ip_address(address)
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        if not ip.is_global or ip.is_multicast:
            raise JobFetchError("host resolves to a non-public address")
        if address not in vetted:
            vetted.append(address)
    return _Hop(parts.scheme, host, port, tuple(vetted))


_PIN = "rt_pinned_address"


class _PinnedTransport(httpx.AsyncBaseTransport):
    """Connects to an address `_check_url` vetted instead of letting the HTTP client
    resolve the name again. A second lookup is the DNS rebinding window: the name can
    answer with a public address for the check and a private one for the connection.

    The pinning happens here, below the client, so the client keeps the real URL: its
    cookie jar stores and replays cookies by host name across redirects, whichever
    address each hop lands on. The Host header and TLS (SNI and certificate check) still
    use the original host name."""

    def __init__(self, inner: httpx.AsyncBaseTransport):
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        address = request.extensions.get(_PIN)
        if address is None:  # never connect by name
            raise httpx.ConnectError("no vetted address for this request", request=request)
        extensions = {k: v for k, v in request.extensions.items() if k != _PIN}
        if request.url.scheme == "https":
            extensions["sni_hostname"] = request.url.raw_host.decode("ascii")
        pinned = httpx.Request(
            request.method, request.url.copy_with(host=address), headers=request.headers,
            stream=request.stream, extensions=extensions,
        )
        return await self._inner.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self._inner.aclose()


async def _send_pinned(client: httpx.AsyncClient, url: str, hop: _Hop) -> httpx.Response:
    """Send to the first vetted address that accepts a connection. The addresses all come
    from the one checked lookup; nothing is resolved again."""
    failure: httpx.HTTPError | None = None
    target = urlsplit(url)._replace(fragment="").geturl()
    for address in hop.addresses[:MAX_ADDRESSES_TRIED]:
        try:
            request = client.build_request("GET", target, extensions={_PIN: address})
            return await client.send(request, stream=True)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            failure = exc
    assert failure is not None
    raise failure


_HTML = ("text/html", ("html", "text/plain"))
_JSON = ("application/json", ("json",))
_TOO_SLOW = "the page took too long to respond"


async def _download_async(
    url: str, *, timeout: float, max_bytes: int, transport: httpx.AsyncBaseTransport | None,
    kind: tuple[str, tuple[str, ...]], deadline: float,
):
    accept, allowed_types = kind
    headers = {"User-Agent": "RoleTailorBot/1.0 (+job description fetch)", "Accept": accept}
    loop = asyncio.get_running_loop()
    pinned = _PinnedTransport(transport or httpx.AsyncHTTPTransport(trust_env=False))
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, trust_env=False, transport=pinned,
        headers=headers,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            hop = await loop.run_in_executor(_DNS_POOL, _check_url, url)
            response = await _send_pinned(client, url, hop)
            try:
                if response.is_redirect and "location" in response.headers:
                    url = urljoin(url, response.headers["location"])
                    continue
                if response.status_code != 200:
                    raise JobFetchError(f"status {response.status_code}")
                content_type = response.headers.get("content-type", "")
                if not any(allowed in content_type for allowed in allowed_types):
                    raise JobFetchError("unsupported content type")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise JobFetchError("response too large")
                    if time.monotonic() > deadline:
                        raise JobFetchError(_TOO_SLOW)
                return bytes(body), response.encoding or "utf-8"
            finally:
                await response.aclose()
    raise JobFetchError("too many redirects")


def _download(
    url: str, *, timeout: float, max_bytes: int, transport: httpx.AsyncBaseTransport | None,
    kind: tuple[str, tuple[str, ...]] = _HTML, deadline: float | None = None,
):
    """`timeout` bounds each connect and read. The deadline bounds the whole fetch (name
    lookups, connects, response headers, body and redirects) by cancelling it, so a server
    that drips bytes, in the headers or the body, cannot hold a request thread open."""
    if deadline is None:
        deadline = time.monotonic() + timeout * 2.5
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise JobFetchError(_TOO_SLOW)
    fetch = _download_async(url, timeout=timeout, max_bytes=max_bytes, transport=transport, kind=kind,
                            deadline=deadline)
    try:
        return asyncio.run(asyncio.wait_for(fetch, remaining))
    except TimeoutError:  # httpx timeouts are httpx.TimeoutException, not this
        raise JobFetchError(_TOO_SLOW) from None


def _clean(text: str) -> str:
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _is_job_posting(item: object) -> bool:
    if not isinstance(item, dict) or not item.get("description"):
        return False
    kind = item.get("@type")
    return "JobPosting" in (kind if isinstance(kind, list) else [kind])


def _json_ld_job(soup: BeautifulSoup) -> FetchedJob | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            graph = data.get("@graph")
            candidates = [data, *(graph if isinstance(graph, list) else [])]
        else:
            continue
        for item in candidates:
            if _is_job_posting(item):
                org = item.get("hiringOrganization")
                return FetchedJob(
                    text=job_boards.html_to_text(item["description"]),
                    title=_str_or_none(item.get("title")),
                    company=_str_or_none(org.get("name")) if isinstance(org, dict) else None,
                )
    return None


def extract_job(html: str, *, structured_only: bool = False) -> FetchedJob:
    soup = BeautifulSoup(html, "html.parser")
    structured = _json_ld_job(soup)
    if structured and len(structured.text) >= MIN_TEXT_CHARS:
        return structured
    if structured_only:
        raise JobFetchError("no structured job posting on the page")
    og_title = soup.find("meta", property="og:title")
    title = (og_title.get("content") if og_title else None) or (
        soup.title.string.strip() if soup.title and soup.title.string else None
    )
    for tag in soup(_NOISE_TAGS):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"}) or soup.body
    text = _clean(main.get_text("\n")) if main else ""
    if len(text) < MIN_TEXT_CHARS:
        raise JobFetchError("no readable job description on the page")
    return FetchedJob(text=text, title=title, company=None)


def _fetch_from_board(
    request: job_boards.BoardRequest, *, timeout: float, max_bytes: int, transport: httpx.AsyncBaseTransport | None,
    deadline: float | None = None,
) -> FetchedJob:
    try:
        body, _ = _download(request.api_url, timeout=timeout, max_bytes=max_bytes, transport=transport, kind=_JSON,
                            deadline=deadline)
        job = request.parse(json.loads(body))
    except httpx.HTTPError as exc:
        # The transport error text can describe internal network state; keep it out of the reply.
        raise JobFetchError(f"could not connect to the {request.board} API") from exc
    except job_boards.BoardParseError as exc:  # our own wording, safe to show
        raise JobFetchError(f"unreadable {request.board} API response: {exc}") from exc
    except (ValueError, RecursionError) as exc:  # RecursionError: absurdly nested JSON
        raise JobFetchError(f"unreadable {request.board} API response") from exc
    if len(job.text) < MIN_TEXT_CHARS:
        raise JobFetchError(f"{request.board} API returned no job description")
    return FetchedJob(text=job.text, title=job.title, company=job.company)


def _fetch_page(
    url: str, *, timeout: float, max_bytes: int, transport: httpx.AsyncBaseTransport | None,
    structured_only: bool = False, deadline: float | None = None,
) -> FetchedJob:
    try:
        body, encoding = _download(url, timeout=timeout, max_bytes=max_bytes, transport=transport,
                                   deadline=deadline)
    except httpx.HTTPError as exc:
        # The transport error text can describe internal network state; keep it out of the reply.
        raise JobFetchError("could not connect to the page") from exc
    return extract_job(body.decode(encoding, errors="replace"), structured_only=structured_only)


def fetch_job_page(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    board_max_bytes: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    total_seconds: float | None = None,
) -> FetchedJob:
    """Fetch a job posting, using the job board's public API when the URL is from a known board.
    `total_seconds` is the wall-clock budget for everything: both attempts and all redirects."""
    deadline = time.monotonic() + (total_seconds if total_seconds is not None else timeout * 2.5)
    board = job_boards.match(url)
    if board is None:
        return _fetch_page(url, timeout=timeout, max_bytes=max_bytes, transport=transport, deadline=deadline)

    def from_api() -> FetchedJob:
        return _fetch_from_board(board, timeout=timeout, max_bytes=board_max_bytes or max_bytes, transport=transport,
                                 deadline=deadline)

    def from_page() -> FetchedJob:
        # On a page-first board the generic text fallback would only see an app shell.
        return _fetch_page(
            url, timeout=timeout, max_bytes=max_bytes, transport=transport, structured_only=board.page_first,
            deadline=deadline,
        )

    first, second = (from_page, from_api) if board.page_first else (from_api, from_page)
    try:
        return first()
    except JobFetchError as exc:
        log.info("job board fetch fell back: board=%s page_first=%s reason=%s", board.board, board.page_first, exc)
    return second()
