"""Fetch a job posting URL safely and extract its main text.

SSRF guards: only http/https, every hop's host must resolve exclusively to public
addresses, redirects are followed manually (and re-checked), proxies from the
environment are ignored, responses are size-capped and time-limited (per read and in
total), and only ports 80 and 443 are allowed. Each connection is made to the exact
address that was checked, so a host cannot pass the check with a public address and
then answer the real lookup with a private one (DNS rebinding).
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

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


def _check_url(url: str) -> tuple[str, str, int, str]:
    """Validate one hop. Returns (scheme, host, port, address), where `address` is the
    vetted public IP the connection must be made to."""
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
        addresses = _resolve(parts.hostname, port)
    except (socket.gaierror, UnicodeError) as exc:
        raise JobFetchError("host does not resolve") from exc
    if not addresses:
        raise JobFetchError("host does not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        if not ip.is_global or ip.is_multicast:
            raise JobFetchError("host resolves to a non-public address")
    return parts.scheme, parts.hostname, port, addresses[0].split("%", 1)[0]


def _pinned_request(client: httpx.Client, url: str) -> httpx.Request:
    """Build a GET that connects to the address `_check_url` vetted instead of letting
    the HTTP client resolve the name again. A second lookup is the DNS rebinding window:
    the name can answer with a public address for the check and a private one for the
    connection. TLS still verifies the certificate against the original host name."""
    scheme, host, port, address = _check_url(url)
    parts = urlsplit(url)
    literal = f"[{address}]" if ":" in address else address
    default_port = 443 if scheme == "https" else 80
    netloc = literal if port == default_port else f"{literal}:{port}"
    target = parts._replace(netloc=netloc, fragment="").geturl()
    host_header = host if port == default_port else f"{host}:{port}"
    extensions = {"sni_hostname": host} if scheme == "https" else {}
    return client.build_request("GET", target, headers={"Host": host_header}, extensions=extensions)


def _download(url: str, *, timeout: float, max_bytes: int, transport: httpx.BaseTransport | None,
              total_seconds: float | None = None):
    headers = {"User-Agent": "RoleTailorBot/1.0 (+job description fetch)", "Accept": "text/html"}
    # `timeout` bounds each connect and read; the deadline bounds the whole fetch, so a
    # server that drips bytes cannot hold a request thread open.
    deadline = time.monotonic() + (total_seconds if total_seconds is not None else timeout * 2.5)
    with httpx.Client(
        timeout=timeout, follow_redirects=False, trust_env=False, transport=transport,
        headers=headers,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            if time.monotonic() > deadline:
                raise JobFetchError("the page took too long to respond")
            response = client.send(_pinned_request(client, url), stream=True)
            try:
                if response.is_redirect and "location" in response.headers:
                    url = urljoin(url, response.headers["location"])
                    continue
                if response.status_code != 200:
                    raise JobFetchError(f"status {response.status_code}")
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type and "text/plain" not in content_type:
                    raise JobFetchError("unsupported content type")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise JobFetchError("response too large")
                    if time.monotonic() > deadline:
                        raise JobFetchError("the page took too long to respond")
                return bytes(body), response.encoding or "utf-8"
            finally:
                response.close()
    raise JobFetchError("too many redirects")


def _clean(text: str) -> str:
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


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
            candidates = [data, *data.get("@graph", [])]
        else:
            continue
        for item in candidates:
            if _is_job_posting(item):
                org = item.get("hiringOrganization")
                text = BeautifulSoup(item["description"], "html.parser").get_text("\n")
                return FetchedJob(
                    text=_clean(text),
                    title=item.get("title"),
                    company=org.get("name") if isinstance(org, dict) else None,
                )
    return None


def extract_job(html: str) -> FetchedJob:
    soup = BeautifulSoup(html, "html.parser")
    structured = _json_ld_job(soup)
    if structured and len(structured.text) >= MIN_TEXT_CHARS:
        return structured
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


def fetch_job_page(
    url: str, *, timeout: float, max_bytes: int, transport: httpx.BaseTransport | None = None,
    total_seconds: float | None = None,
) -> FetchedJob:
    try:
        body, encoding = _download(url, timeout=timeout, max_bytes=max_bytes, transport=transport,
                                   total_seconds=total_seconds)
    except httpx.HTTPError as exc:
        # The transport error text can describe internal network state; keep it out of the reply.
        raise JobFetchError("could not connect to the page") from exc
    return extract_job(body.decode(encoding, errors="replace"))
