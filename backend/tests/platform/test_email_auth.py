"""Email verification and password reset: tokens, enumeration, sessions, limits, provider."""

from __future__ import annotations

import json
import re
import secrets

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from roletailor import mailer
from roletailor.api.ratelimit import RateLimiter
from roletailor.config import get_settings
from roletailor.mailer import templates
from roletailor.services import email_auth

PASSWORD = "correct horse battery"
NEW_PASSWORD = "a brand new passphrase"


@pytest.fixture()
def outbox(app):
    provider = mailer.get_provider()
    assert isinstance(provider, mailer.MemoryProvider)
    provider.outbox.clear()
    return provider.outbox


def _token(message: mailer.EmailMessage, page: str) -> str:
    match = re.search(rf"/{page}#token=(\S+)", message.text)
    assert match, message.text
    assert match.group(1) in message.html
    return match.group(1)


def _last(outbox, kind: str, to: str) -> mailer.EmailMessage:
    found = [m for m in outbox if m.kind == kind and m.to == to]
    assert found, [(m.kind, m.to) for m in outbox]
    return found[-1]


def _sql(database: str, query: str, params: tuple = ()) -> list[tuple]:
    owner = get_settings().migration_database_url.rsplit("/", 1)[0] + f"/{database}"
    with psycopg.connect(owner, autocommit=True) as conn:
        cur = conn.execute(query, params)
        return cur.fetchall() if cur.description else []


def _login(client, email: str, password: str):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


# --- Verification ------------------------------------------------------------------------


def test_signup_sends_a_link_that_verifies_once(client, make_user, outbox, database):
    user = make_user(consent=False)
    assert user.get("/v1/me").json()["email_verified_at"] is None
    token = _token(_last(outbox, "verify_email", user.email), "verify-email")

    # Only a hash is stored.
    stored = _sql(database, "SELECT token_hash FROM roletailor.user_tokens WHERE user_id = %s", (user.id,))
    assert stored and all(token not in row[0] and row[0] != token for row in stored)

    assert client.post("/v1/auth/verify-email", json={"token": token}).json() == {"status": "verified"}
    assert user.get("/v1/me").json()["email_verified_at"] is not None

    again = client.post("/v1/auth/verify-email", json={"token": token})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_token"
    assert user.post("/v1/auth/verify-email/resend").json() == {"status": "already_verified"}


def test_bad_expired_and_superseded_verification_tokens(client, make_user, outbox, database):
    user = make_user(consent=False)
    first = _token(_last(outbox, "verify_email", user.email), "verify-email")

    for junk in ("nope", "a.b", first[:-1] + ("A" if first[-1] != "A" else "B"), "x" * 200):
        r = client.post("/v1/auth/verify-email", json={"token": junk})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_token", junk

    resend = user.post("/v1/auth/verify-email/resend")
    assert resend.status_code == 202 and resend.json() == {"status": "sent"}
    second = _token(_last(outbox, "verify_email", user.email), "verify-email")
    assert second != first
    assert client.post("/v1/auth/verify-email", json={"token": first}).status_code == 400  # superseded

    _sql(database, "UPDATE roletailor.user_tokens SET created_at = now() - interval '3 days',"
                   " expires_at = now() - interval '1 minute' WHERE user_id = %s", (user.id,))
    assert client.post("/v1/auth/verify-email", json={"token": second}).status_code == 400  # expired
    assert user.get("/v1/me").json()["email_verified_at"] is None


def test_token_is_bound_to_its_purpose_and_address(client, make_user, outbox, database):
    user = make_user(consent=False)
    verify = _token(_last(outbox, "verify_email", user.email), "verify-email")
    # A verification token cannot reset a password.
    r = client.post("/v1/auth/reset-password", json={"token": verify, "password": NEW_PASSWORD})
    assert r.status_code == 400
    assert _login(client, user.email, PASSWORD).status_code == 200

    # The link stops working once the account's address is no longer the one it was sent to.
    _sql(database, "UPDATE roletailor.users SET email = %s WHERE id = %s",
         (f"moved-{secrets.token_hex(4)}@example.com", user.id))
    assert client.post("/v1/auth/verify-email", json={"token": verify}).status_code == 400
    assert user.get("/v1/me").json()["email_verified_at"] is None


def test_generation_needs_a_verified_email(client, make_user, outbox, monkeypatch):
    monkeypatch.setattr(get_settings(), "require_verified_email", True)
    user = make_user()  # consent given, email not yet confirmed
    body = {"resume_id": "00000000-0000-0000-0000-000000000000",
            "job_posting_id": "00000000-0000-0000-0000-000000000000"}
    blocked = user.post("/v1/workflows", json=body)
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "email_unverified"
    assert user.get("/v1/resumes").status_code == 200  # everything else stays open

    token = _token(_last(outbox, "verify_email", user.email), "verify-email")
    assert client.post("/v1/auth/verify-email", json={"token": token}).status_code == 200
    after = user.post("/v1/workflows", json=body)
    assert after.status_code != 403 or after.json()["error"]["code"] != "email_unverified"


def test_signup_survives_an_email_outage(client, monkeypatch):
    class Down:
        def send(self, message):
            raise mailer.EmailSendError("down")

    monkeypatch.setattr(mailer, "get_provider", lambda: Down())
    email = f"user-{secrets.token_hex(6)}@example.com"
    r = client.post("/v1/auth/register", json={"email": email, "password": PASSWORD, "full_name": "Ada"})
    assert r.status_code == 201
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    resend = client.post("/v1/auth/verify-email/resend", headers=headers)
    assert resend.status_code == 503 and resend.json()["error"]["code"] == "email_unavailable"


def test_resend_is_rate_limited_and_needs_a_session(client, make_user, monkeypatch):
    assert client.post("/v1/auth/verify-email/resend").status_code == 401
    monkeypatch.setattr(get_settings(), "rate_limit_verification_email_per_hour", 2)
    user = make_user(consent=False)
    codes = [user.post("/v1/auth/verify-email/resend").status_code for _ in range(3)]
    assert codes == [202, 202, 429]


# --- Password reset ----------------------------------------------------------------------


def test_forgot_password_does_not_reveal_accounts(client, make_user, outbox):
    user = make_user(consent=False)
    outbox.clear()
    known = client.post("/v1/auth/forgot-password", json={"email": user.email.upper()})
    unknown = client.post("/v1/auth/forgot-password", json={"email": f"nobody-{secrets.token_hex(4)}@example.com"})
    malformed = client.post("/v1/auth/forgot-password", json={"email": "not an address"})
    for r in (known, unknown, malformed):
        assert r.status_code == 202 and r.json() == {"status": "accepted"}
    assert {(m.kind, m.to) for m in outbox} == {("reset_password", user.email)}


def test_reset_changes_password_and_signs_out_everywhere(client, make_user, outbox, database):
    user = make_user(consent=False)
    second_session = _login(client, user.email, PASSWORD).json()["token"]
    client.post("/v1/auth/forgot-password", json={"email": user.email})
    token = _token(_last(outbox, "reset_password", user.email), "reset-password")

    weak = client.post("/v1/auth/reset-password", json={"token": token, "password": "short"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "weak_password"

    done = client.post("/v1/auth/reset-password", json={"token": token, "password": NEW_PASSWORD})
    assert done.status_code == 200 and done.json() == {"status": "password_reset"}  # weak try did not burn it

    assert user.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {second_session}"}).status_code == 401
    assert _login(client, user.email, PASSWORD).status_code == 401
    fresh = _login(client, user.email, NEW_PASSWORD)
    assert fresh.status_code == 200
    assert fresh.json()["user"]["email_verified_at"] is not None  # the link proved the inbox

    replay = client.post("/v1/auth/reset-password", json={"token": token, "password": "yet another passphrase"})
    assert replay.status_code == 400 and replay.json()["error"]["code"] == "invalid_token"
    assert _login(client, user.email, NEW_PASSWORD).status_code == 200

    assert _last(outbox, "password_changed", user.email)
    actions = _sql(database, "SELECT action, metadata FROM roletailor.audit_logs WHERE actor_user_id = %s"
                             " AND action = 'auth.password_reset'", (user.id,))
    assert len(actions) == 1 and actions[0][1]["sessions_revoked"] == 2


def test_only_the_newest_reset_link_works_and_links_expire(client, make_user, outbox, database):
    user = make_user(consent=False)
    client.post("/v1/auth/forgot-password", json={"email": user.email})
    first = _token(_last(outbox, "reset_password", user.email), "reset-password")
    client.post("/v1/auth/forgot-password", json={"email": user.email})
    second = _token(_last(outbox, "reset_password", user.email), "reset-password")
    assert client.post("/v1/auth/reset-password", json={"token": first, "password": NEW_PASSWORD}).status_code == 400

    _sql(database, "UPDATE roletailor.user_tokens SET created_at = now() - interval '2 hours',"
                   " expires_at = now() - interval '1 second' WHERE user_id = %s", (user.id,))
    assert client.post("/v1/auth/reset-password", json={"token": second, "password": NEW_PASSWORD}).status_code == 400
    assert _login(client, user.email, PASSWORD).status_code == 200


def test_concurrent_use_of_one_link_succeeds_once(make_user, outbox, client):
    from concurrent.futures import ThreadPoolExecutor

    user = make_user(consent=False)
    client.post("/v1/auth/forgot-password", json={"email": user.email})
    token = _token(_last(outbox, "reset_password", user.email), "reset-password")

    def attempt(i: int) -> bool:
        try:
            email_auth.reset_password(token, f"parallel passphrase {i}")
        except Exception:
            return False
        return True

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert results.count(True) == 1


def test_forgot_password_limits(app, make_user, outbox, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_password_reset_per_hour", 2)
    monkeypatch.setattr(get_settings(), "rate_limit_auth_per_minute", 4)
    original = app.state.limiter
    app.state.limiter = RateLimiter("redis://127.0.0.1:1/0", prefix=f"rl-{secrets.token_hex(4)}")  # memory fallback
    try:
        with TestClient(app) as client:
            email = f"user-{secrets.token_hex(6)}@example.com"
            client.post("/v1/auth/register", json={"email": email, "password": PASSWORD, "full_name": "Ada"})
            outbox.clear()
            codes = [client.post("/v1/auth/forgot-password", json={"email": email}).status_code for _ in range(5)]
        # Per address: quietly dropped after two, still 202. Per client: refused after four.
        assert codes == [202, 202, 202, 202, 429]
        assert len([m for m in outbox if m.kind == "reset_password"]) == 2
    finally:
        app.state.limiter = original


# --- Provider and configuration --------------------------------------------------------------


def _message() -> mailer.EmailMessage:
    return templates.password_reset("ada@example.com", "Ada Lovelace", "https://app.test/reset-password#token=t.s", 60)


def test_templates_escape_names_and_carry_the_link():
    message = templates.verification("ada@example.com", "<script>x</script> Ada", "https://app.test/v#token=a.b", 24)
    assert "<script>" not in message.html and "&lt;script&gt;" in message.html
    assert "https://app.test/v#token=a.b" in message.text and "24 hours" in message.text
    changed = templates.password_changed("a@example.com", None, "https://app.test/forgot-password")
    assert changed.text.startswith("Hi there,")


def test_resend_provider_sends_and_retries_with_one_idempotency_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(503 if len(seen) == 1 else 200, json={"id": "email_1"})

    provider = mailer.ResendProvider("re_test_key", "RoleTailor <no-reply@mail.test>", "help@mail.test",
                                     client=httpx.Client(transport=httpx.MockTransport(handler)), backoff_seconds=0)
    provider.send(_message())
    assert len(seen) == 2 and str(seen[0].url) == "https://api.resend.com/emails"
    assert seen[0].headers["authorization"] == "Bearer re_test_key"
    assert seen[0].headers["idempotency-key"] == seen[1].headers["idempotency-key"]
    payload = json.loads(seen[0].content)
    assert payload["from"] == "RoleTailor <no-reply@mail.test>" and payload["to"] == ["ada@example.com"]
    assert payload["reply_to"] == "help@mail.test" and payload["text"] and payload["html"]


def test_resend_provider_fails_without_leaking_the_message():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(422, json={"name": "validation_error", "message": "bad ada@example.com"})

    provider = mailer.ResendProvider("re_test_key", "a@mail.test",
                                     client=httpx.Client(transport=httpx.MockTransport(handler)), backoff_seconds=0)
    with pytest.raises(mailer.EmailSendError) as err:
        provider.send(_message())
    assert len(calls) == 1  # a rejected request is not retried
    assert "validation_error" in str(err.value)
    assert "ada@example.com" not in str(err.value) and "token" not in str(err.value)


def test_console_provider_logs_the_link(caplog):
    with caplog.at_level("INFO", logger="roletailor.mailer.provider"):
        mailer.ConsoleProvider().send(_message())
    assert "reset-password#token=t.s" in caplog.text



def test_concurrent_issuance_leaves_one_live_link(make_user, outbox, database):
    from concurrent.futures import ThreadPoolExecutor

    user = make_user(consent=False)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: email_auth.request_password_reset(user.email), range(8)))
    live = _sql(database, "SELECT count(*) FROM roletailor.user_tokens WHERE user_id = %s"
                          " AND purpose = 'reset_password' AND used_at IS NULL", (user.id,))
    assert live[0][0] == 1


def test_login_racing_a_reset_never_keeps_a_session(client, make_user, outbox, database):
    """A login with the old password either lands before the reset (and is revoked by it)
    or after it (and is refused). No session may survive the reset."""
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import suppress

    from roletailor.services import auth as auth_service
    from roletailor.services.errors import AppError

    for _ in range(4):
        user = make_user(consent=False)
        client.post("/v1/auth/forgot-password", json={"email": user.email})
        token = _token(_last(outbox, "reset_password", user.email), "reset-password")

        def old_login(_, email=user.email):
            with suppress(AppError):
                auth_service.login(email, PASSWORD, "race")

        with ThreadPoolExecutor(max_workers=5) as pool:
            logins = [pool.submit(old_login, i) for i in range(4)]
            reset = pool.submit(email_auth.reset_password, token, NEW_PASSWORD)
            reset.result()
            [f.result() for f in logins]
        active = _sql(database, "SELECT count(*) FROM roletailor.sessions WHERE user_id = %s"
                                " AND revoked_at IS NULL", (user.id,))
        assert active[0][0] == 0
