"""Job board API handlers: URL detection, payload normalisation, guards and fallbacks."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from roletailor.services import job_boards, job_fetch

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "job_boards"
UUID = "7458d4e9-da2e-47bd-98cb-adfda43d42b2"
LEVER_ID = "6ed76ce8-4156-4b60-b120-403538bd66cd"
PUBLIC_IP = "93.184.216.34"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(("url", "board", "api_url"), [
    ("https://boards.greenhouse.io/exampleco/jobs/8172510", "greenhouse",
     "https://boards-api.greenhouse.io/v1/boards/exampleco/jobs/8172510"),
    ("https://job-boards.greenhouse.io/exampleco/jobs/8172510?gh_src=abc#app", "greenhouse",
     "https://boards-api.greenhouse.io/v1/boards/exampleco/jobs/8172510"),
    ("https://boards.greenhouse.io/embed/job_app?for=exampleco&token=8172510", "greenhouse",
     "https://boards-api.greenhouse.io/v1/boards/exampleco/jobs/8172510"),
    (f"https://jobs.lever.co/exampleco/{LEVER_ID}", "lever", f"https://api.lever.co/v0/postings/exampleco/{LEVER_ID}"),
    (f"https://jobs.lever.co/exampleco/{LEVER_ID.upper()}/apply?lever-source=x", "lever",
     f"https://api.lever.co/v0/postings/exampleco/{LEVER_ID}"),
    (f"https://jobs.eu.lever.co/exampleco/{LEVER_ID}", "lever",
     f"https://api.eu.lever.co/v0/postings/exampleco/{LEVER_ID}"),
    (f"https://jobs.ashbyhq.com/ExampleCo/{UUID}/application", "ashby",
     "https://api.ashbyhq.com/posting-api/job-board/ExampleCo"),
    ("https://jobs.smartrecruiters.com/ExampleGroup/744000163611949-machine-learning-engineer?oga=true",
     "smartrecruiters", "https://api.smartrecruiters.com/v1/companies/ExampleGroup/postings/744000163611949"),
    ("HTTPS://WWW.Jobs.SmartRecruiters.com/ExampleGroup/744000163611949", "smartrecruiters",
     "https://api.smartrecruiters.com/v1/companies/ExampleGroup/postings/744000163611949"),
])
def test_match_builds_the_api_url(url, board, api_url):
    request = job_boards.match(url)
    assert request is not None and (request.board, request.api_url) == (board, api_url)
    assert request.page_first is (board == "ashby")


@pytest.mark.parametrize("url", [
    "https://example.com/careers/123",
    "https://stripe.com/jobs/search?gh_jid=8172510",       # custom domain: board token unknown
    "https://boards.greenhouse.io/exampleco",              # board index, not a posting
    "https://boards.greenhouse.io/exampleco/jobs/abc",
    "https://boards.greenhouse.io/..%2f..%2fadmin/jobs/1/",
    "https://boards.greenhouse.io/example co/jobs/1",
    "https://jobs.lever.co/exampleco",
    "https://jobs.lever.co/exampleco/not-a-uuid",
    f"https://jobs.lever.co/a?b/{LEVER_ID}",
    "https://jobs.ashbyhq.com/ExampleCo",
    "https://jobs.smartrecruiters.com/ExampleGroup/machine-learning-engineer",
    "https://evil.example.com/boards.greenhouse.io/exampleco/jobs/1",
    "https://boards.greenhouse.io.evil.example.com/exampleco/jobs/1",
    "ftp://jobs.lever.co/exampleco/" + LEVER_ID,
    "not a url",
])
def test_match_ignores_other_urls(url):
    assert job_boards.match(url) is None


def test_html_to_text_keeps_blocks_and_inline_text_together():
    text = job_boards.html_to_text(
        "<h2>Role</h2><p>Hi I’m <a href='#'><u>Colin</u></a>, Director.<br>Second&nbsp;line</p>"
        "<ul><li><p>First</p></li><li>Second <strong>bold</strong></li></ul><script>x()</script>"
    )
    assert text == "Role\nHi I’m Colin, Director.\nSecond line\n- First\n- Second bold"
    assert job_boards.html_to_text(None) == "" and job_boards.html_to_text(42) == ""


def _serve(monkeypatch, routes: dict[str, httpx.Response]):
    """Mock transport keyed by full URL; records every request made."""
    monkeypatch.setattr(job_fetch, "_resolve", lambda host, port: [PUBLIC_IP])
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return routes.get(str(request.url), httpx.Response(404, json={"error": "not found"}))

    return httpx.MockTransport(handler), seen


def _json(name: str) -> httpx.Response:
    return httpx.Response(200, content=fixture(name).encode(), headers={"content-type": "application/json"})


def _fetch(url: str, transport, **overrides):
    options = {"timeout": 1, "max_bytes": 100_000, "transport": transport} | overrides
    return job_fetch.fetch_job_page(url, **options)


def test_greenhouse_posting(monkeypatch):
    api = "https://boards-api.greenhouse.io/v1/boards/exampleco/jobs/8172510"
    transport, seen = _serve(monkeypatch, {api: _json("greenhouse_job.json")})
    job = _fetch("https://job-boards.greenhouse.io/exampleco/jobs/8172510", transport)
    assert (job.title, job.company) == ("Senior Data Engineer", "ExampleCo")
    assert seen == [api]
    lines = job.text.splitlines()
    assert lines[0] == "Who we are" and "What you’ll do" in lines
    assert "- Build and operate Kafka pipelines at scale" in lines and "- Model data in Snowflake & dbt" in lines
    assert "It's a small team" in job.text and "&lt;" not in job.text and "<" not in job.text


def test_lever_posting(monkeypatch):
    api = f"https://api.lever.co/v0/postings/exampleco/{LEVER_ID}"
    transport, seen = _serve(monkeypatch, {api: _json("lever_posting.json")})
    job = _fetch(f"https://jobs.lever.co/exampleco/{LEVER_ID}/apply", transport)
    assert (job.title, job.company) == ("Data Engineer", None) and seen == [api]
    assert job.text.count("A World-Changing Company") == 1  # the opening is not duplicated
    assert "Core Responsibilities\n- Build streaming pipelines with Kafka and Spark." in job.text
    assert "What We Require\n- At least three years" in job.text
    assert job.text.rstrip().endswith("We offer hybrid work.")


def test_smartrecruiters_posting(monkeypatch):
    api = "https://api.smartrecruiters.com/v1/companies/ExampleGroup/postings/744000163611949"
    transport, seen = _serve(monkeypatch, {api: _json("smartrecruiters_posting.json")})
    job = _fetch("https://jobs.smartrecruiters.com/ExampleGroup/744000163611949-machine-learning-engineer", transport)
    assert (job.title, job.company) == ("Machine Learning Engineer", "Example Group") and seen == [api]
    assert "Job Description\nYou will design" in job.text
    assert "Qualifications\n- MSc in Computer Science or similar\n- 3+ years of MLOps experience" in job.text
    assert "Additional Information" not in job.text  # empty sections are dropped


def test_ashby_reads_the_page_first_and_skips_the_board_api(monkeypatch):
    page = f"https://jobs.ashbyhq.com/ExampleCo/{UUID}"
    transport, seen = _serve(monkeypatch, {
        page: httpx.Response(200, text=fixture("ashby_job_page.html"), headers={"content-type": "text/html"}),
    })
    job = _fetch(page, transport)
    assert (job.title, job.company) == ("Analytics Engineer", "ExampleCo") and seen == [page]
    assert "Hi 👋 I’m Colin, Director of Engineering." in job.text and "- Expert SQL and dbt" in job.text


def test_ashby_falls_back_to_the_board_api(monkeypatch):
    page = f"https://jobs.ashbyhq.com/ExampleCo/{UUID}"
    api = "https://api.ashbyhq.com/posting-api/job-board/ExampleCo"
    shell = "<html><body><div id='root'></div><main>" + "Loading the application shell. " * 20 + "</main></body></html>"
    transport, seen = _serve(monkeypatch, {
        page: httpx.Response(200, text=shell, headers={"content-type": "text/html"}),
        api: _json("ashby_job_board.json"),
    })
    job = _fetch(page, transport, max_bytes=1_000, board_max_bytes=100_000)  # the API gets its own, larger cap
    assert (job.title, job.company) == ("Analytics Engineer", None) and seen == [page, api]
    assert "Experience with Airflow" in job.text and "Account Executive" not in job.text

    missing = f"https://jobs.ashbyhq.com/ExampleCo/{UUID[:-1]}0"
    with pytest.raises(job_fetch.JobFetchError, match="not found on the Ashby job board"):
        _fetch(missing, transport, board_max_bytes=100_000)


LONG = "Build reliable data pipelines with Kafka and Spark. " * 10
GENERIC_PAGE = httpx.Response(
    200, headers={"content-type": "text/html"},
    text=f"<html><head><title>Data Engineer</title></head><body><main><p>{LONG}</p></main></body></html>",
)


@pytest.mark.parametrize("api_response", [
    httpx.Response(404, json={"status": 404, "error": "Job not found"}),
    httpx.Response(200, text="<html>maintenance</html>", headers={"content-type": "text/html"}),
    httpx.Response(200, text="not json", headers={"content-type": "application/json"}),
    httpx.Response(200, json=["unexpected"]),
    httpx.Response(200, json={"title": "Empty", "content": "&lt;p&gt;Too short&lt;/p&gt;"}),
    httpx.Response(200, json={"content": "x" * 200_000}),  # over the size cap
])
def test_api_failure_falls_back_to_the_posting_page(monkeypatch, api_response):
    page = "https://boards.greenhouse.io/exampleco/jobs/8172510"
    api = "https://boards-api.greenhouse.io/v1/boards/exampleco/jobs/8172510"
    transport, seen = _serve(monkeypatch, {api: api_response, page: GENERIC_PAGE})
    job = _fetch(page, transport)
    assert job.title == "Data Engineer" and "Kafka" in job.text and seen == [api, page]


def test_both_paths_failing_raises_the_page_error(monkeypatch):
    transport, seen = _serve(monkeypatch, {})
    with pytest.raises(job_fetch.JobFetchError, match="status 404"):
        _fetch(f"https://jobs.lever.co/exampleco/{LEVER_ID}", transport)
    assert len(seen) == 2


def test_api_requests_keep_the_ssrf_guards(monkeypatch):
    """The API host is resolved and checked like any other, and so is every redirect hop."""
    api = f"https://api.lever.co/v0/postings/exampleco/{LEVER_ID}"
    page = f"https://jobs.lever.co/exampleco/{LEVER_ID}"
    addresses = {"api.lever.co": PUBLIC_IP, "jobs.lever.co": PUBLIC_IP, "internal.example.com": "10.0.0.5"}
    checked: list[str] = []

    def resolve(host, port):
        checked.append(host)
        return [addresses[host]]

    monkeypatch.setattr(job_fetch, "_resolve", resolve)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == api:
            return httpx.Response(302, headers={"location": "http://internal.example.com/latest/meta-data"})
        return httpx.Response(404)

    with pytest.raises(job_fetch.JobFetchError):
        _fetch(page, httpx.MockTransport(handler))
    assert checked == ["api.lever.co", "internal.example.com", "jobs.lever.co"]
    assert seen == [api, page]  # the internal redirect target was never requested

    # An API host that resolves to a private address is refused before any request.
    addresses["api.lever.co"] = "169.254.169.254"
    seen.clear()
    with pytest.raises(job_fetch.JobFetchError):
        _fetch(page, httpx.MockTransport(handler))
    assert seen == [page]


# --- Optional live smoke test -------------------------------------------------------------
# Hits the real public APIs. Off by default; run with:
#   RT_LIVE_JOB_BOARDS=1 pytest tests/platform/test_job_boards.py -m live

def _live_greenhouse(client: httpx.Client) -> str:
    job = client.get("https://boards-api.greenhouse.io/v1/boards/stripe/jobs").json()["jobs"][0]
    return f"https://boards.greenhouse.io/stripe/jobs/{job['id']}"


def _live_lever(client: httpx.Client) -> str:
    return client.get("https://api.lever.co/v0/postings/palantir?mode=json&limit=1").json()[0]["hostedUrl"]


def _live_ashby(client: httpx.Client) -> str:
    return client.get("https://api.ashbyhq.com/posting-api/job-board/ashby").json()["jobs"][0]["jobUrl"]


def _live_smartrecruiters(client: httpx.Client) -> str:
    posting = client.get("https://api.smartrecruiters.com/v1/companies/BoschGroup/postings?limit=1").json()["content"][0]
    return f"https://jobs.smartrecruiters.com/BoschGroup/{posting['id']}"


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("RT_LIVE_JOB_BOARDS") != "1", reason="set RT_LIVE_JOB_BOARDS=1 to hit real APIs")
@pytest.mark.parametrize("find_url", [_live_greenhouse, _live_lever, _live_ashby, _live_smartrecruiters],
                         ids=["greenhouse", "lever", "ashby", "smartrecruiters"])
def test_live_posting_is_fetched(find_url):
    with httpx.Client(timeout=30) as client:
        url = find_url(client)
    assert job_boards.match(url) is not None, url
    job = job_fetch.fetch_job_page(url, timeout=20, max_bytes=2 * 1024 * 1024, board_max_bytes=8 * 1024 * 1024)
    assert job.title and len(job.text) >= 500, (url, job.title, len(job.text))
    assert "<p" not in job.text and "&lt;" not in job.text
    print(json.dumps({"url": url, "title": job.title, "company": job.company, "chars": len(job.text)}))
