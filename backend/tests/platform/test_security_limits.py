"""Abuse limits added by the pre-launch security audit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from roletailor.api import deps
from roletailor.api.bodylimit import limit_for
from roletailor.config import get_settings


def _request(headers: dict[str, str], peer: str = "172.16.0.9") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": (peer, 1234), "method": "GET", "path": "/"})


@pytest.fixture
def settings(monkeypatch):
    def apply(**values):
        for key, value in values.items():
            monkeypatch.setenv(f"RT_{key.upper()}", str(value))
        get_settings.cache_clear()

    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()


def test_forwarded_for_is_never_trusted(settings):
    settings(client_ip_header="Fly-Client-IP", proxy_shared_secret="s" * 40)
    spoofed = _request({"X-Forwarded-For": "1.2.3.4", "X-RT-Client-IP": "5.6.7.8"})
    assert deps.client_ip(spoofed) == "172.16.0.9"
    wrong_secret = _request({"X-RT-Client-IP": "5.6.7.8", "X-RT-Proxy-Secret": "nope",
                             "Fly-Client-IP": "203.0.113.7"})
    assert deps.client_ip(wrong_secret) == "203.0.113.7"


def test_web_app_relays_the_browser_address_with_the_shared_secret(settings):
    settings(client_ip_header="Fly-Client-IP", proxy_shared_secret="s" * 40)
    relayed = _request({"X-RT-Client-IP": "198.51.100.20", "X-RT-Proxy-Secret": "s" * 40,
                        "Fly-Client-IP": "203.0.113.7"})
    assert deps.client_ip(relayed) == "198.51.100.20"
    garbage = _request({"X-RT-Client-IP": "not-an-ip", "X-RT-Proxy-Secret": "s" * 40,
                        "Fly-Client-IP": "203.0.113.7"})
    assert deps.client_ip(garbage) == "203.0.113.7"


def test_ipv6_clients_share_a_bucket_per_64(settings):
    settings(client_ip_header="Fly-Client-IP")
    a = deps.client_ip(_request({"Fly-Client-IP": "2001:db8:1:2:aaaa::1"}))
    b = deps.client_ip(_request({"Fly-Client-IP": "2001:db8:1:2:bbbb::2"}))
    assert a == b == "2001:db8:1:2::"


def test_body_limits_by_route():
    cfg = get_settings()
    assert limit_for("POST", "/v1/resumes") > cfg.max_upload_bytes
    assert limit_for("POST", "/v1/resumes/text") == cfg.max_json_body_bytes
    assert limit_for("POST", "/v1/billing/webhook") == 1_000_000


def test_oversized_bodies_get_413(client: TestClient, make_user):
    headers = make_user().headers
    big = "x" * (get_settings().max_json_body_bytes + 10)
    declared = client.post("/v1/jobs", json={"description": big}, headers=headers)
    assert declared.status_code == 413 and declared.json()["error"]["code"] == "payload_too_large"

    def chunks():
        yield b'{"description": "'
        for _ in range(60):
            yield b"y" * 10_000
        yield b'"}'

    streamed = client.post("/v1/jobs", content=chunks(), headers={**headers, "content-type": "application/json"})
    assert streamed.status_code == 413
    oversized = b"%PDF-" + b"0" * (get_settings().max_upload_bytes + 70_000)
    too_big_upload = client.post("/v1/resumes", headers=headers, files={"file": ("r.pdf", oversized)})
    assert too_big_upload.status_code == 413


def test_per_user_limit_on_job_fetch_and_uploads(client: TestClient, make_user, settings):
    headers = make_user().headers
    settings(rate_limit_job_per_minute=2, rate_limit_upload_per_minute=1)
    text = "Senior data engineer building reliable pipelines with Kafka and Spark. " * 5
    codes = [client.post("/v1/jobs", json={"description": text}, headers=headers).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    resume = "Experienced engineer. " * 30
    codes = [client.post("/v1/resumes/text", json={"text": resume}, headers=headers).status_code for _ in range(2)]
    assert codes == [201, 429]


def test_daily_generation_cap_is_per_organization(client: TestClient, make_user, settings):
    headers = make_user().headers
    settings(generation_runs_per_org_per_day=1)
    body = {"resume_version_id": "00000000-0000-0000-0000-000000000001",
            "job_posting_id": "00000000-0000-0000-0000-000000000002"}
    first = client.post("/v1/workflows", json=body, headers=headers)
    second = client.post("/v1/workflows", json=body, headers=headers)
    assert first.status_code != 429
    assert second.status_code == 429 and "today" in second.json()["error"]["message"]


def test_metrics_hidden_from_the_public_edge(client: TestClient, settings):
    assert client.get("/metrics").status_code == 200
    settings(client_ip_header="Fly-Client-IP")
    assert client.get("/metrics", headers={"Fly-Client-IP": "203.0.113.7"}).status_code == 404
    assert client.get("/metrics").status_code == 200
    settings(client_ip_header="Fly-Client-IP", metrics_token="t" * 32)
    assert client.get("/metrics").status_code == 404
    assert client.get("/metrics", headers={"Authorization": "Bearer " + "t" * 32,
                                           "Fly-Client-IP": "203.0.113.7"}).status_code == 200


def test_readiness_reports_tenant_isolation(client: TestClient):
    body = client.get("/readyz").json()
    assert body["checks"]["tenant_isolation"] == "ok"


def test_socket_peer_is_bucketed_like_any_other_address(settings):
    settings(client_ip_header="", proxy_shared_secret="")
    assert deps.client_ip(_request({}, peer="2001:db8:1:2:aaaa:bbbb:cccc:dddd")) == "2001:db8:1:2::"
    assert deps.client_ip(_request({}, peer="::ffff:198.51.100.4")) == "198.51.100.4"
    assert deps.client_ip(_request({}, peer="testclient")) == "testclient"


def test_body_limit_rejections_carry_cors_headers(client: TestClient):
    origin = get_settings().cors_origins[0]
    huge = client.post("/v1/auth/login", content=b"x", headers={
        "Content-Type": "application/json", "Content-Length": str(50 * 1024 * 1024), "Origin": origin})
    assert huge.status_code == 413
    assert huge.headers.get("access-control-allow-origin") == origin
