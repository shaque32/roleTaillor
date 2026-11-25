from __future__ import annotations

import secrets

from fastapi.testclient import TestClient

from roletailor.api.ratelimit import RateLimiter


def test_register_login_logout(client, make_user):
    user = make_user(consent=False)
    me = user.get("/v1/me")
    assert me.status_code == 200
    assert me.json()["email"] == user.email
    assert me.json()["consents"] == {"ai_processing": False}

    bad = client.post("/v1/auth/login", json={"email": user.email, "password": "wrong password!"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_credentials"

    good = client.post("/v1/auth/login", json={"email": user.email.upper(), "password": "correct horse battery"},
                       headers={"User-Agent": "pytest-device"})
    assert good.status_code == 200
    body = good.json()
    assert body["token"] and body["expires_at"] and body["organization"]["role"] == "owner"
    headers = {"Authorization": f"Bearer {body['token']}"}
    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/v1/me", headers=headers).status_code == 401
    assert user.get("/v1/me").status_code == 200  # other sessions survive


def test_duplicate_email_and_weak_password(client, make_user):
    user = make_user()
    dup = client.post("/v1/auth/register", json={"email": user.email, "password": "another long pw", "full_name": "X"})
    assert dup.status_code == 409
    weak = client.post("/v1/auth/register", json={"email": "new@example.com", "password": "short", "full_name": "X"})
    assert weak.json()["error"]["code"] == "weak_password"


def test_profile_update(make_user):
    user = make_user()
    r = user.patch("/v1/me", json={"preferred_page_limit": 1, "resume_tone": "confident",
                                   "address": {"city": "London"}})
    assert r.status_code == 200, r.text
    assert r.json()["preferred_page_limit"] == 1 and r.json()["address"] == {"city": "London"}


def test_unauthenticated_and_correlation_id(client):
    r = client.get("/v1/me", headers={"X-Correlation-ID": "abc-123"})
    assert r.status_code == 401
    assert r.headers["X-Correlation-ID"] == "abc-123"
    assert r.json()["error"]["code"] == "unauthorized"
    assert len(client.get("/healthz").headers["X-Correlation-ID"]) == 32


def test_login_rate_limit(app, monkeypatch):
    from roletailor.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_auth_per_minute", 2)
    original = app.state.limiter
    app.state.limiter = RateLimiter("redis://127.0.0.1:1/0", prefix=f"rl-{secrets.token_hex(4)}")  # memory fallback
    try:
        with TestClient(app) as client:
            codes = [client.post("/v1/auth/login", json={"email": "a@b.co", "password": "x"}).status_code
                     for _ in range(3)]
        assert codes == [401, 401, 429]
    finally:
        app.state.limiter = original
